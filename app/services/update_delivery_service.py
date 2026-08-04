from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

import app
from app.config.runtime import RuntimeConfig
from app.models.update_delivery import (
    UpdateCheckSnapshot,
    UpdateDeliveryGate,
    UpdateDownloadArtifact,
    UpdateDownloadReceipt,
    UpdatePreferences,
)
from app.services.final_release_service import FinalReleaseService


class UpdateDeliveryService:
    """Check, verify and stage updates without installing or restarting the app."""

    PREFERENCES_SCHEMA = 1
    STATE_SCHEMA = 1
    RECEIPT_SCHEMA = 1
    MAX_FEED_BYTES = 2 * 1024 * 1024
    MAX_NOTES_BYTES = 512 * 1024
    MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
    CHANNELS = FinalReleaseService.CHANNELS
    SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        current_version: str | None = None,
        client: httpx.Client | None = None,
        signature_verifier: Callable[[Path], tuple[bool, str]] | None = None,
        machine_id: str | None = None,
    ) -> None:
        self.runtime = runtime
        self.current_version = current_version or app.__version__
        self.preferences_path = runtime.settings_path.parent / "update-delivery.json"
        self.state_path = runtime.settings_path.parent / "update-delivery-state.json"
        self.machine_id_path = runtime.settings_path.parent / "update-client-id.txt"
        self.download_root = runtime.cache_dir / "updates"
        self.receipt_root = runtime.artifacts_dir / "update-delivery"
        self._client = client
        self._signature_verifier = signature_verifier or self._verify_authenticode
        self._machine_id_override = machine_id

    def default_preferences(self) -> UpdatePreferences:
        return UpdatePreferences()

    def load_preferences(self) -> UpdatePreferences:
        payload = self._json(self.preferences_path)
        if not payload:
            return self.default_preferences()
        try:
            return self._validated_preferences(
                UpdatePreferences(
                    enabled=bool(payload.get("enabled", True)),
                    check_on_startup=bool(payload.get("check_on_startup", False)),
                    channel=str(payload.get("channel") or "preview"),
                    feed_url=str(payload.get("feed_url") or ""),
                    check_interval_hours=int(payload.get("check_interval_hours", 24)),
                    prefer_installer=bool(payload.get("prefer_installer", True)),
                )
            )
        except (TypeError, ValueError):
            return self.default_preferences()

    def save_preferences(self, preferences: UpdatePreferences) -> UpdatePreferences:
        validated = self._validated_preferences(preferences)
        self._write_json(
            self.preferences_path,
            {
                "schema_version": self.PREFERENCES_SCHEMA,
                **validated.to_dict(),
            },
        )
        return validated

    def should_check_on_startup(self, now: datetime | None = None) -> bool:
        preferences = self.load_preferences()
        if not (
            preferences.enabled
            and preferences.check_on_startup
            and preferences.feed_url.strip()
        ):
            return False
        state = self._json(self.state_path)
        last_raw = str(state.get("last_checked_at") or "")
        if not last_raw:
            return True
        try:
            last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        current = now or datetime.now(timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return current - last >= timedelta(hours=preferences.check_interval_hours)

    def check_for_updates(
        self,
        feed_source: str | Path | None = None,
        *,
        force: bool = False,
    ) -> UpdateCheckSnapshot:
        preferences = self.load_preferences()
        source = str(feed_source or preferences.feed_url).strip()
        captured_at = self._now()
        check_id = self._check_id(captured_at, source)
        if not force and not preferences.enabled:
            return UpdateCheckSnapshot(
                check_id=check_id,
                captured_at=captured_at,
                current_version=self.current_version,
                latest_version="",
                channel=preferences.channel,
                status="disabled",
                summary="Update checks are disabled by the user.",
                feed_source=source,
            )
        if not source:
            return self._blocked(
                check_id,
                captured_at,
                preferences.channel,
                source,
                "No update feed has been configured.",
                "Configure an HTTPS update feed or choose a verified local feed.",
            )

        gates: list[UpdateDeliveryGate] = []
        try:
            feed_bytes, resolved_source = self._read_resource(
                source,
                limit=self.MAX_FEED_BYTES,
            )
            digest_text, _ = self._read_resource(
                self._digest_source(resolved_source),
                limit=4096,
            )
            expected_digest = digest_text.decode("ascii", errors="strict").split()[0]
            actual_digest = hashlib.sha256(feed_bytes).hexdigest()
            digest_ok = bool(self.SHA256_RE.fullmatch(expected_digest)) and secrets.compare_digest(
                actual_digest.casefold(), expected_digest.casefold()
            )
            gates.append(
                self._gate(
                    "feed_integrity",
                    "Update feed SHA-256",
                    digest_ok,
                    "blocker",
                    (
                        "Update feed digest is verified."
                        if digest_ok
                        else "Update feed digest is missing, malformed or does not match."
                    ),
                    "Publish the feed with its matching SHA-256 digest.",
                )
            )
            if not digest_ok:
                raise ValueError("update feed digest mismatch")
            payload = json.loads(feed_bytes.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("Update feed root must be an object.")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, httpx.HTTPError) as exc:
            self._record_check(captured_at, "error", source)
            return self._blocked(
                check_id,
                captured_at,
                preferences.channel,
                source,
                f"Update feed could not be verified: {exc}",
                "Check the feed URL, TLS connection and digest file.",
                gates=tuple(gates),
            )

        schema_ok = payload.get("schema_version") == 1
        gates.append(
            self._gate(
                "feed_schema",
                "Update feed schema",
                schema_ok,
                "blocker",
                "Schema version 1 is supported." if schema_ok else "Unsupported update feed schema.",
                "Publish the update feed using schema version 1.",
            )
        )
        product_ok = str(payload.get("product") or "") == "S Talking"
        gates.append(
            self._gate(
                "product_identity",
                "Update product identity",
                product_ok,
                "blocker",
                (
                    "Update feed targets S Talking."
                    if product_ok
                    else "Update feed targets a different or unnamed product."
                ),
                "Publish the feed with product identity 'S Talking'.",
            )
        )
        try:
            channel = FinalReleaseService.normalize_channel(str(payload.get("channel") or ""))
        except ValueError:
            channel = str(payload.get("channel") or "invalid")
        channel_ok = channel == preferences.channel
        gates.append(
            self._gate(
                "channel_identity",
                "Selected update channel",
                channel_ok,
                "blocker",
                (
                    f"Feed channel matches {channel}."
                    if channel_ok
                    else f"Feed channel {channel} does not match selected channel {preferences.channel}."
                ),
                "Use the feed published for the selected channel.",
            )
        )

        latest_version = str(payload.get("version") or "").strip()
        version_ok = bool(latest_version) and self._parse_version(latest_version) is not None
        gates.append(
            self._gate(
                "version_identity",
                "Update version identity",
                version_ok,
                "blocker",
                f"Feed advertises version {latest_version}." if version_ok else "Feed version is invalid.",
                "Publish a valid numeric semantic version with an optional prerelease suffix.",
            )
        )
        stable_ok = channel != "stable" or not self._is_prerelease(latest_version)
        gates.append(
            self._gate(
                "stable_policy",
                "Stable channel prerelease policy",
                stable_ok,
                "blocker",
                (
                    "Stable channel version policy is satisfied."
                    if stable_ok
                    else "A prerelease version cannot be delivered through the stable channel."
                ),
                "Move prerelease builds to preview or beta.",
            )
        )

        rollout = self._bounded_int(payload.get("rollout_percentage"), 1, 100, 100)
        critical = bool(payload.get("critical", False))
        bucket = self.rollout_bucket(channel, latest_version)
        eligible = critical or bucket < rollout
        gates.append(
            self._gate(
                "staged_rollout",
                "Staged rollout eligibility",
                eligible,
                "warning",
                (
                    f"Client bucket {bucket} is eligible for the {rollout}% rollout."
                    if eligible
                    else f"Client bucket {bucket} is outside the current {rollout}% rollout."
                ),
                "Wait for rollout expansion or perform an explicit forced check for diagnostics.",
            )
        )

        artifacts, artifact_gates = self._parse_artifacts(
            payload.get("artifacts"),
            latest_version,
        )
        gates.extend(artifact_gates)
        selected = self._select_artifact(artifacts, preferences.prefer_installer)
        gates.append(
            self._gate(
                "download_artifact",
                "Downloadable update artifact",
                selected is not None,
                "blocker",
                (
                    f"Selected {selected.filename}."
                    if selected
                    else "No supported portable package or Windows installer is available."
                ),
                "Publish a canonical portable ZIP or Windows installer.",
            )
        )

        notes, notes_url, notes_gate = self._release_notes(payload, resolved_source)
        gates.append(notes_gate)
        minimum_supported = str(payload.get("minimum_supported_version") or "").strip()
        minimum_ok = (
            not minimum_supported
            or (
                self._parse_version(minimum_supported) is not None
                and self._compare_versions(self.current_version, minimum_supported) >= 0
            )
        )
        gates.append(
            self._gate(
                "minimum_supported_version",
                "Minimum supported version",
                minimum_ok,
                "blocker",
                (
                    f"Current version {self.current_version} satisfies the minimum requirement."
                    if minimum_ok
                    else f"Current version {self.current_version} is older than required {minimum_supported}."
                ),
                "Use the documented recovery or full installer path for unsupported versions.",
            )
        )

        blockers = sum(g.severity == "blocker" and not g.passed for g in gates)
        newer = version_ok and self._compare_versions(latest_version, self.current_version) > 0
        if blockers:
            status = "blocked"
            summary = "Update metadata failed one or more security or compatibility gates."
        elif not newer:
            status = "current"
            summary = f"S Talking {self.current_version} is up to date on the {channel} channel."
        elif not eligible:
            status = "deferred"
            summary = f"Version {latest_version} is available but not yet assigned to this staged rollout bucket."
        else:
            status = "available"
            summary = f"Version {latest_version} is available for controlled download."

        snapshot = UpdateCheckSnapshot(
            check_id=check_id,
            captured_at=captured_at,
            current_version=self.current_version,
            latest_version=latest_version,
            channel=channel,
            status=status,
            summary=summary,
            feed_source=resolved_source,
            published_at=str(payload.get("published_at") or ""),
            rollout_percentage=rollout,
            rollout_bucket=bucket,
            eligible=eligible,
            critical=critical,
            minimum_supported_version=minimum_supported,
            release_notes=notes,
            release_notes_url=notes_url,
            selected_artifact=selected,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )
        self._record_check(captured_at, status, resolved_source, latest_version)
        self.export_snapshot(snapshot)
        return snapshot

    def download_update(self, snapshot: UpdateCheckSnapshot) -> UpdateCheckSnapshot:
        if not snapshot.update_available or snapshot.selected_artifact is None:
            raise RuntimeError("No eligible verified update is available for download.")
        artifact = snapshot.selected_artifact
        target_dir = self.download_root / snapshot.channel / snapshot.latest_version
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / artifact.filename
        partial = target_dir / f".{target.stem}.partial{target.suffix}"
        partial.unlink(missing_ok=True)
        try:
            self._download_resource(
                snapshot.feed_source,
                artifact,
                partial,
            )
            actual_size = partial.stat().st_size
            actual_sha = self._sha256(partial)
            if actual_size != artifact.size_bytes:
                raise RuntimeError(
                    f"Downloaded size mismatch: expected {artifact.size_bytes}, got {actual_size}."
                )
            if not secrets.compare_digest(actual_sha, artifact.sha256.casefold()):
                raise RuntimeError("Downloaded artifact SHA-256 does not match the update feed.")
            signature_status = artifact.signature_status
            if artifact.filename.casefold().endswith(".exe"):
                verified, detail = self._signature_verifier(partial)
                if signature_status == "verified" and not verified:
                    raise RuntimeError(f"Authenticode verification failed: {detail}")
                signature_status = "verified" if verified else "unsigned"
            os.replace(partial, target)
            receipt = UpdateDownloadReceipt(
                receipt_id=self._receipt_id(snapshot, artifact),
                created_at=self._now(),
                check_id=snapshot.check_id,
                version=snapshot.latest_version,
                channel=snapshot.channel,
                artifact_role=artifact.role,
                artifact_path=target,
                size_bytes=actual_size,
                sha256=actual_sha,
                signature_status=signature_status,
                status="verified",
                detail="Artifact downloaded and verified. Installation was not started.",
            )
            self._write_receipt(receipt)
            updated = replace(
                snapshot,
                downloaded_path=target,
                summary=(
                    f"{artifact.filename} was downloaded and verified. Installation remains under user control."
                ),
            )
            self.export_snapshot(updated)
            return updated
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    def install_plan(self, snapshot: UpdateCheckSnapshot) -> dict[str, object]:
        path = snapshot.downloaded_path
        if path is None or not path.exists():
            return {
                "allowed": False,
                "reason": "No verified downloaded artifact is available.",
                "command": [],
            }
        if path.suffix.casefold() == ".exe":
            verified, detail = self._signature_verifier(path)
            if not verified:
                return {
                    "allowed": False,
                    "reason": f"Installer signature is not verified: {detail}",
                    "command": [],
                }
            return {
                "allowed": True,
                "reason": "Verified installer is ready. The user must explicitly launch it.",
                "command": [str(path)],
                "requires_confirmation": True,
                "automatic_restart": False,
            }
        return {
            "allowed": True,
            "reason": "Verified portable package is ready for manual extraction.",
            "command": ["explorer.exe", f"/select,{path}"],
            "requires_confirmation": True,
            "automatic_restart": False,
        }

    def rollout_bucket(self, channel: str, version: str) -> int:
        material = f"{self.machine_id()}\n{channel}\n{version}".encode("utf-8")
        return int(hashlib.sha256(material).hexdigest()[:8], 16) % 100

    def machine_id(self) -> str:
        if self._machine_id_override:
            return self._machine_id_override
        try:
            value = self.machine_id_path.read_text(encoding="ascii").strip()
            if re.fullmatch(r"[0-9a-f]{32}", value):
                return value
        except OSError:
            pass
        value = secrets.token_hex(16)
        self.machine_id_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.machine_id_path, value + "\n", encoding="ascii")
        return value

    def export_snapshot(self, snapshot: UpdateCheckSnapshot) -> Path:
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        path = self.receipt_root / "latest-update-check.json"
        self._write_json(path, snapshot.to_dict())
        return path

    def _release_notes(
        self,
        payload: dict[str, Any],
        feed_source: str,
    ) -> tuple[str, str, UpdateDeliveryGate]:
        notes = str(payload.get("release_notes") or "").strip()
        notes_url = str(payload.get("release_notes_url") or "").strip()
        notes_sha = str(payload.get("release_notes_sha256") or "").strip().casefold()
        if notes:
            return notes[:20000], "", self._gate(
                "release_notes",
                "Release notes",
                True,
                "warning",
                "Release notes are embedded in the verified feed.",
                "",
            )
        if not notes_url:
            return "", "", self._gate(
                "release_notes",
                "Release notes",
                False,
                "warning",
                "No release notes are included with this update.",
                "Publish concise release notes with the update feed.",
            )
        if not self._safe_relative_name(notes_url) or not self.SHA256_RE.fullmatch(notes_sha):
            return "", notes_url, self._gate(
                "release_notes",
                "Release notes",
                False,
                "warning",
                "Release notes metadata is unsafe or missing a SHA-256 digest.",
                "Publish release notes as a relative filename with a valid digest.",
            )
        try:
            source = self._sibling_source(feed_source, notes_url)
            data, _ = self._read_resource(source, limit=self.MAX_NOTES_BYTES)
            digest_ok = secrets.compare_digest(hashlib.sha256(data).hexdigest(), notes_sha)
            if not digest_ok:
                raise ValueError("release notes digest mismatch")
            text = data.decode("utf-8-sig").strip()
        except (OSError, UnicodeError, ValueError, httpx.HTTPError) as exc:
            return "", notes_url, self._gate(
                "release_notes",
                "Release notes",
                False,
                "warning",
                f"Release notes could not be verified: {exc}",
                "Republish the notes and matching digest.",
            )
        return text[:20000], notes_url, self._gate(
            "release_notes",
            "Release notes",
            True,
            "warning",
            "Release notes were downloaded and verified.",
            "",
        )

    def _parse_artifacts(
        self,
        raw: object,
        version: str,
    ) -> tuple[list[UpdateDownloadArtifact], list[UpdateDeliveryGate]]:
        artifacts: list[UpdateDownloadArtifact] = []
        gates: list[UpdateDeliveryGate] = []
        seen_roles: set[str] = set()
        seen_names: set[str] = set()
        if not isinstance(raw, list):
            return artifacts, [
                self._gate(
                    "artifact_metadata",
                    "Update artifact metadata",
                    False,
                    "blocker",
                    "Feed artifacts must be a list.",
                    "Publish at least one canonical update artifact.",
                )
            ]
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            filename = str(item.get("filename") or "").strip()
            url = str(item.get("url") or "").strip()
            sha256 = str(item.get("sha256") or "").strip().casefold()
            try:
                size = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            expected_name = {
                "portable_package": f"S-Talking-{version}-portable.zip",
                "windows_installer": f"S-Talking-{version}-setup.exe",
            }.get(role, "")
            signature_status = str(
                item.get("signature_status") or "not_applicable"
            ).strip().casefold()
            valid = (
                bool(expected_name)
                and filename == expected_name
                and self._safe_relative_name(filename)
                and url == filename
                and role not in seen_roles
                and filename not in seen_names
                and 0 < size <= self.MAX_ARTIFACT_BYTES
                and bool(self.SHA256_RE.fullmatch(sha256))
                and signature_status
                in {"verified", "unsigned", "unavailable", "not_applicable"}
            )
            gates.append(
                self._gate(
                    f"artifact_{index}",
                    f"Artifact {filename or index + 1}",
                    valid,
                    "blocker",
                    (
                        f"{filename} metadata is safe and complete."
                        if valid
                        else "Artifact metadata has a non-canonical or duplicate name, unsafe path, unsupported role, invalid size, invalid digest or invalid signature status."
                    ),
                    "Use a relative filename, exact size and SHA-256 digest.",
                )
            )
            if valid:
                seen_roles.add(role)
                seen_names.add(filename)
                artifacts.append(
                    UpdateDownloadArtifact(
                        role=role,
                        filename=filename,
                        url=url,
                        size_bytes=size,
                        sha256=sha256,
                        signature_status=signature_status,
                    )
                )
        return artifacts, gates

    @staticmethod
    def _select_artifact(
        artifacts: list[UpdateDownloadArtifact],
        prefer_installer: bool,
    ) -> UpdateDownloadArtifact | None:
        order = (
            ("windows_installer", "portable_package")
            if prefer_installer
            else ("portable_package", "windows_installer")
        )
        for role in order:
            match = next((item for item in artifacts if item.role == role), None)
            if match is not None:
                return match
        return None

    def _download_resource(
        self,
        feed_source: str,
        artifact: UpdateDownloadArtifact,
        target: Path,
    ) -> None:
        source = self._sibling_source(feed_source, artifact.url)
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            self._validate_remote_url(source, "artifact")
            client = self._client or httpx.Client(
                timeout=httpx.Timeout(60.0, connect=15.0),
                follow_redirects=True,
            )
            close_client = self._client is None
            try:
                with client.stream("GET", source) as response:
                    response.raise_for_status()
                    resolved = str(response.url)
                    self._validate_remote_url(resolved, "artifact redirect")
                    if urlparse(resolved).netloc != parsed.netloc:
                        raise ValueError("Update artifact redirected away from the feed origin.")
                    total = 0
                    with target.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > min(artifact.size_bytes, self.MAX_ARTIFACT_BYTES):
                                raise ValueError("Downloaded artifact exceeds declared size.")
                            handle.write(chunk)
            finally:
                if close_client:
                    client.close()
            return
        path = self._local_path(source)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        with path.open("rb") as source_handle, target.open("wb") as target_handle:
            total = 0
            while chunk := source_handle.read(1024 * 1024):
                total += len(chunk)
                if total > min(artifact.size_bytes, self.MAX_ARTIFACT_BYTES):
                    raise ValueError("Local update artifact exceeds declared size.")
                target_handle.write(chunk)

    def _read_resource(self, source: str, *, limit: int) -> tuple[bytes, str]:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            self._validate_remote_url(source, "metadata")
            client = self._client or httpx.Client(
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
            )
            close_client = self._client is None
            try:
                response = client.get(source)
                response.raise_for_status()
                data = response.content
                if len(data) > limit:
                    raise ValueError("Remote update metadata exceeds the size limit.")
                resolved = str(response.url)
                self._validate_remote_url(resolved, "metadata redirect")
                if urlparse(resolved).netloc != parsed.netloc:
                    raise ValueError("Update metadata redirected away from the configured origin.")
                return data, resolved
            finally:
                if close_client:
                    client.close()
        path = self._local_path(source)
        data = path.read_bytes()
        if len(data) > limit:
            raise ValueError("Local update metadata exceeds the size limit.")
        return data, str(path.resolve())

    @staticmethod
    def _local_path(source: str) -> Path:
        if UpdateDeliveryService._is_windows_path(source):
            return Path(source).expanduser()
        parsed = urlparse(source)
        if parsed.scheme == "file":
            return Path(parsed.path.lstrip("/") if os.name == "nt" else parsed.path)
        if parsed.scheme:
            raise ValueError(f"Unsupported update source scheme: {parsed.scheme}")
        return Path(source).expanduser()

    @classmethod
    def _digest_source(cls, feed_source: str) -> str:
        parsed = urlparse(feed_source)
        name = (
            cls._local_path(feed_source).name
            if cls._is_windows_path(feed_source) or not parsed.scheme or parsed.scheme == "file"
            else Path(parsed.path).name
        )
        digest_name = "latest.sha256" if name == "latest.json" else "update-feed.sha256"
        return cls._sibling_source(feed_source, digest_name)

    @staticmethod
    def _sibling_source(source: str, filename: str) -> str:
        if not UpdateDeliveryService._safe_relative_name(filename):
            raise ValueError("Update resource filename is unsafe.")
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            base = source.rsplit("/", 1)[0] + "/"
            joined = urljoin(base, filename)
            if urlparse(joined).netloc != parsed.netloc:
                raise ValueError("Update resource escaped the feed origin.")
            return joined
        path = UpdateDeliveryService._local_path(source)
        return str(path.parent / filename)

    @staticmethod
    def _is_windows_path(source: str) -> bool:
        return bool(re.match(r"^[A-Za-z]:[\\/]", source)) or source.startswith("\\\\")

    @staticmethod
    def _safe_relative_name(value: str) -> bool:
        if not value or "\\" in value or "/" in value:
            return False
        path = Path(value)
        return path.name == value and not path.is_absolute() and ".." not in path.parts

    @staticmethod
    def _validate_remote_url(source: str, label: str) -> None:
        parsed = urlparse(source)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Remote update {label} requires HTTPS.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                f"Remote update {label} cannot contain credentials, query strings or fragments."
            )

    def _validated_preferences(self, value: UpdatePreferences) -> UpdatePreferences:
        channel = FinalReleaseService.normalize_channel(value.channel)
        interval = max(1, min(int(value.check_interval_hours), 24 * 30))
        feed_url = value.feed_url.strip()
        if feed_url and not self._is_windows_path(feed_url):
            parsed = urlparse(feed_url)
            if parsed.scheme == "https":
                self._validate_remote_url(feed_url, "feed")
            elif parsed.scheme and parsed.scheme != "file":
                raise ValueError("Update feed must use HTTPS or a local file path.")
        return replace(
            value,
            channel=channel,
            feed_url=feed_url,
            check_interval_hours=interval,
        )

    def _blocked(
        self,
        check_id: str,
        captured_at: str,
        channel: str,
        source: str,
        detail: str,
        remediation: str,
        *,
        gates: tuple[UpdateDeliveryGate, ...] = (),
    ) -> UpdateCheckSnapshot:
        combined = gates + (
            self._gate(
                "feed_access",
                "Update feed access",
                False,
                "blocker",
                detail,
                remediation,
            ),
        )
        snapshot = UpdateCheckSnapshot(
            check_id=check_id,
            captured_at=captured_at,
            current_version=self.current_version,
            latest_version="",
            channel=channel,
            status="blocked",
            summary=detail,
            feed_source=source,
            gates=combined,
        )
        self.export_snapshot(snapshot)
        return snapshot

    def _record_check(
        self,
        captured_at: str,
        status: str,
        source: str,
        version: str = "",
    ) -> None:
        self._write_json(
            self.state_path,
            {
                "schema_version": self.STATE_SCHEMA,
                "last_checked_at": captured_at,
                "last_status": status,
                "last_feed_source": source,
                "last_version": version,
            },
        )

    def _write_receipt(self, receipt: UpdateDownloadReceipt) -> Path:
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        path = self.receipt_root / f"{receipt.receipt_id}.json"
        self._write_json(
            path,
            {
                "schema_version": self.RECEIPT_SCHEMA,
                **receipt.to_dict(),
            },
        )
        return path

    @staticmethod
    def _parse_version(value: str) -> tuple[int, int, int, int, int] | None:
        match = re.fullmatch(
            r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:(?:-|\.?)(dev|preview|a|alpha|b|beta|rc)(\d+)?)?\s*",
            value,
            re.IGNORECASE,
        )
        if not match:
            return None
        major, minor, patch = (int(match.group(i) or 0) for i in range(1, 4))
        label = (match.group(4) or "").casefold()
        rank = {
            "dev": -1,
            "preview": -1,
            "a": 0,
            "alpha": 0,
            "b": 1,
            "beta": 1,
            "rc": 2,
            "": 3,
        }[label]
        serial = int(match.group(5) or 0)
        return major, minor, patch, rank, serial

    @classmethod
    def _compare_versions(cls, left: str, right: str) -> int:
        left_key = cls._parse_version(left)
        right_key = cls._parse_version(right)
        if left_key is None or right_key is None:
            return (left.casefold() > right.casefold()) - (left.casefold() < right.casefold())
        return (left_key > right_key) - (left_key < right_key)

    @classmethod
    def _is_prerelease(cls, value: str) -> bool:
        parsed = cls._parse_version(value)
        return bool(parsed and parsed[3] < 3)

    @staticmethod
    def _bounded_int(value: object, minimum: int, maximum: int, default: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(resolved, maximum))

    @staticmethod
    def _gate(
        code: str,
        label: str,
        passed: bool,
        severity: str,
        detail: str,
        remediation: str,
    ) -> UpdateDeliveryGate:
        return UpdateDeliveryGate(
            code=code,
            label=label,
            status="passed" if passed else "failed",
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _check_id(captured_at: str, source: str) -> str:
        digest = hashlib.sha256(f"{captured_at}\n{source}".encode("utf-8")).hexdigest()[:12]
        return f"update-{digest}"

    @staticmethod
    def _receipt_id(
        snapshot: UpdateCheckSnapshot,
        artifact: UpdateDownloadArtifact,
    ) -> str:
        digest = hashlib.sha256(
            f"{snapshot.check_id}\n{artifact.sha256}".encode("ascii")
        ).hexdigest()[:12]
        return f"download-{digest}"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        self._atomic_write(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _atomic_write(path: Path, text: str, *, encoding: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding=encoding)
        os.replace(temporary, path)

    @staticmethod
    def _verify_authenticode(path: Path) -> tuple[bool, str]:
        if sys.platform != "win32":
            return False, "Authenticode verification is only available on Windows."
        command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "$s=Get-AuthenticodeSignature -LiteralPath $args[0];"
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                "$s | Select-Object Status,StatusMessage | ConvertTo-Json -Compress"
            ),
            str(path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            payload = json.loads(result.stdout.strip() or "{}")
            status = str(payload.get("Status") or "Unknown")
            detail = str(payload.get("StatusMessage") or status)
            return status.casefold() == "valid", detail
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            return False, str(exc)
