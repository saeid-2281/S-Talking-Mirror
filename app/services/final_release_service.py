from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app
from app.config.runtime import RuntimeConfig
from app.models.final_release import (
    FinalReleaseArtifact,
    FinalReleaseGate,
    FinalReleaseSnapshot,
    SigningEvidence,
    UpdateArtifact,
)
from app.release import RELEASE_CHANNEL
from app.services.distribution_readiness_service import DistributionReadinessService


class FinalReleaseService:
    """Stage signed release evidence and deterministic update-channel metadata."""

    MANIFEST_NAME = "final-release-manifest.json"
    CHECKSUM_NAME = "SHA256SUMS.txt"
    RESULT_NAME = "final-release-result.json"
    FEED_DIGEST_NAME = "update-feed.sha256"
    SIGNING_RESULT_NAME = "signing-result.json"
    CHANNELS = {"preview", "beta", "stable"}
    CHANNEL_ALIASES = {"rc": "preview", "dev": "preview", "development": "preview"}
    SENSITIVE_NAMES = {
        "settings.json",
        "api-profiles.json",
        "workspace-profiles.json",
        "s-talking.db",
        "s_talking.db",
    }

    def __init__(
        self,
        runtime: RuntimeConfig,
        distribution_service: DistributionReadinessService,
        *,
        version: str | None = None,
        release_channel: str = RELEASE_CHANNEL,
    ) -> None:
        self.runtime = runtime
        self.distribution_service = distribution_service
        self.version = version or app.__version__
        self.release_channel = release_channel
        self.root = runtime.artifacts_dir / "final-release"
        self.channel_root = runtime.artifacts_dir / "update-channel"

    def latest_release_dir(self) -> Path:
        return self.root / "latest"

    def latest_channel_feed(self, channel: str | None = None) -> Path:
        return self.channel_root / self.normalize_channel(channel or self.release_channel) / "latest.json"

    @classmethod
    def normalize_channel(cls, channel: str) -> str:
        value = str(channel or "").strip().casefold()
        value = cls.CHANNEL_ALIASES.get(value, value)
        if value not in cls.CHANNELS:
            raise ValueError(f"Unsupported update channel: {channel}")
        return value

    def snapshot(
        self,
        distribution_dir: Path | None = None,
        *,
        channel: str | None = None,
        rollout_percentage: int = 100,
    ) -> FinalReleaseSnapshot:
        source = Path(distribution_dir or self.distribution_service.latest_distribution_dir())
        resolved_channel = self.normalize_channel(channel or self.release_channel)
        rollout = self._rollout(rollout_percentage)
        gates: list[FinalReleaseGate] = []
        signatures = self._signing_evidence()
        artifacts: list[FinalReleaseArtifact] = []

        manifest = source / self.distribution_service.MANIFEST_NAME
        distribution_ok = False
        distribution_detail = "No verified distribution candidate is available."
        if manifest.exists():
            distribution_ok, distribution_detail = self.distribution_service.verify_distribution_manifest(
                manifest
            )
        gates.append(
            self._gate(
                "verified_distribution",
                "Verified distribution candidate",
                distribution_ok,
                "blocker",
                distribution_detail,
                "Build and verify the Phase 52 distribution candidate first.",
            )
        )

        payload = self._json(manifest)
        listed = self._listed_artifacts(source, payload)
        for role, path in listed.items():
            if path.exists():
                artifacts.append(
                    self._artifact(role, path, self._signature_status(role, signatures))
                )

        portable = listed.get("portable_package")
        portable_ok = bool(portable and portable.exists() and portable.name == f"S-Talking-{self.version}-portable.zip")
        gates.append(
            self._gate(
                "portable_release",
                "Portable release package",
                portable_ok,
                "blocker",
                (
                    f"Portable package is ready: {portable.name}"
                    if portable_ok and portable
                    else "The canonical portable package is missing or has the wrong versioned filename."
                ),
                "Rebuild the Phase 52 package from the current application version.",
            )
        )

        installer = listed.get("windows_installer")
        installer_ok = bool(installer and self._is_pe(installer))
        gates.append(
            self._gate(
                "windows_installer",
                "Windows installer artifact",
                installer_ok,
                "warning",
                (
                    f"Installer is available: {installer.name}"
                    if installer_ok and installer
                    else "No compiled Windows installer is included; release remains portable-only."
                ),
                "Install Inno Setup and rebuild packages to include a Windows installer.",
            )
        )

        executable_signature = self._signature(signatures, "application_executable")
        installer_signature = self._signature(signatures, "windows_installer")
        executable_signature_ok = executable_signature.verified and self._evidence_integrity(
            executable_signature
        )
        installer_signature_ok = installer_signature.verified and self._evidence_integrity(
            installer_signature
        )
        gates.append(
            self._gate(
                "application_signature",
                "Application executable signature",
                executable_signature_ok,
                "warning",
                executable_signature.detail or "S-Talking.exe is not Authenticode signed.",
                "Configure a code-signing certificate thumbprint and SignTool, then rebuild.",
            )
        )
        gates.append(
            self._gate(
                "installer_signature",
                "Installer Authenticode signature",
                installer_ok and installer_signature_ok,
                "warning",
                (
                    installer_signature.detail
                    if installer_ok
                    else "Installer signature cannot be verified because no installer is included."
                ),
                "Sign and timestamp the installer with the configured code-signing certificate.",
            )
        )
        timestamp_ok = all(
            evidence.timestamped
            for evidence in signatures
            if evidence.role in {"application_executable", "windows_installer"}
            and evidence.verified
            and self._evidence_integrity(evidence)
        ) and any(
            item.verified and self._evidence_integrity(item) for item in signatures
        )
        gates.append(
            self._gate(
                "signature_timestamp",
                "Signature timestamp evidence",
                timestamp_ok,
                "warning",
                (
                    "Verified signatures include timestamp evidence."
                    if timestamp_ok
                    else "No timestamped Authenticode signature evidence is available."
                ),
                "Set S_TALKING_TIMESTAMP_URL and rebuild signed artifacts.",
            )
        )

        version_ok = str(payload.get("version") or "") == self.version
        gates.append(
            self._gate(
                "version_identity",
                "Release version identity",
                version_ok,
                "blocker",
                (
                    f"Distribution version matches {self.version}."
                    if version_ok
                    else "Distribution manifest version does not match the running release tools."
                ),
                "Rebuild release and distribution evidence from one clean commit.",
            )
        )

        privacy_ok, privacy_detail = self._privacy_audit(source)
        gates.append(
            self._gate(
                "release_privacy",
                "Release bundle privacy",
                privacy_ok,
                "blocker",
                privacy_detail,
                "Remove settings, credentials, databases, reports, logs and generated outputs.",
            )
        )

        channel_ok = resolved_channel in self.CHANNELS and 1 <= rollout <= 100
        gates.append(
            self._gate(
                "update_channel",
                "Update channel policy",
                channel_ok,
                "blocker",
                f"Channel {resolved_channel} uses a {rollout}% staged rollout.",
                "Choose preview, beta or stable and a rollout percentage from 1 to 100.",
            )
        )
        stable_ok = resolved_channel != "stable" or "-" not in self.version
        gates.append(
            self._gate(
                "stable_version_policy",
                "Stable channel version policy",
                stable_ok,
                "blocker",
                (
                    "Prerelease version is correctly restricted to a non-stable channel."
                    if resolved_channel != "stable"
                    else "Stable channel version does not contain a prerelease suffix."
                    if stable_ok
                    else "Prerelease versions cannot be published to the stable channel."
                ),
                "Publish release candidates to preview or beta, or remove the prerelease suffix.",
            )
        )

        status = self._status(gates)
        summary = self._summary(status, installer_ok, installer_signature_ok)
        return FinalReleaseSnapshot(
            release_id=self._release_id(source, resolved_channel),
            version=self.version,
            channel=resolved_channel,
            captured_at=self._now(),
            status=status,
            summary=summary,
            source_distribution=source if source.exists() else None,
            rollout_percentage=rollout,
            gates=tuple(gates),
            signatures=tuple(signatures),
            artifacts=tuple(artifacts),
        )

    def build_final_release(
        self,
        distribution_dir: Path | None = None,
        *,
        channel: str | None = None,
        rollout_percentage: int = 100,
        require_installer: bool = False,
        require_signatures: bool = False,
    ) -> FinalReleaseSnapshot:
        initial = self.snapshot(
            distribution_dir,
            channel=channel,
            rollout_percentage=rollout_percentage,
        )
        if initial.blocker_count:
            raise RuntimeError(initial.summary)
        if initial.source_distribution is None:
            raise FileNotFoundError("Distribution candidate directory is missing.")
        installer_gate_passed = any(
            item.code == "windows_installer" and item.passed for item in initial.gates
        )
        if require_installer and not installer_gate_passed:
            raise RuntimeError("A compiled Windows installer is required for final release packaging.")
        signature_gates = {
            item.code: item.passed
            for item in initial.gates
            if item.code in {
                "application_signature",
                "installer_signature",
                "signature_timestamp",
            }
        }
        signatures_ready = all(signature_gates.get(code, False) for code in (
            "application_signature",
            "installer_signature",
            "signature_timestamp",
        ))
        if require_signatures and not signatures_ready:
            raise RuntimeError(
                "Verified and timestamped application and installer signatures are required."
            )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        bundle = self.root / f"S-Talking-{self.version}-{initial.channel}-{stamp}"
        bundle.mkdir(parents=True, exist_ok=False)

        copied: list[FinalReleaseArtifact] = []
        signing_source = (
            self.runtime.artifacts_dir / "package" / self.SIGNING_RESULT_NAME
        )
        if signing_source.exists():
            signing_target = bundle / self.SIGNING_RESULT_NAME
            shutil.copy2(signing_source, signing_target)
            copied.append(self._artifact("signing_evidence", signing_target))

        for source in sorted(initial.source_distribution.iterdir()):
            if not source.is_file() or source.name == self.distribution_service.RESULT_NAME:
                continue
            target_name = (
                "distribution-SHA256SUMS.txt"
                if source.name == self.distribution_service.CHECKSUM_NAME
                else source.name
            )
            target = bundle / target_name
            shutil.copy2(source, target)
            role = self._role_for_name(source.name)
            copied.append(
                self._artifact(role, target, self._signature_status(role, initial.signatures))
            )

        feed = bundle / f"S-Talking-{initial.channel}.json"
        update_artifacts = [
            UpdateArtifact(
                role=item.role,
                filename=item.path.name,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                url=item.path.name,
                signature_status=item.signature_status,
            )
            for item in copied
            if item.role in {"portable_package", "windows_installer"}
        ]
        feed_payload = {
            "schema_version": 1,
            "product": "S Talking",
            "channel": initial.channel,
            "version": self.version,
            "published_at": self._now(),
            "rollout_percentage": initial.rollout_percentage,
            "minimum_supported_version": "0.18.0",
            "critical": False,
            "source_distribution_id": self._json(
                initial.source_distribution / self.distribution_service.MANIFEST_NAME
            ).get("distribution_id", ""),
            "artifacts": [item.to_dict() for item in update_artifacts],
        }
        self._write_json(feed, feed_payload)
        feed_digest = bundle / self.FEED_DIGEST_NAME
        feed_digest.write_text(f"{self._sha256(feed)}  {feed.name}\n", encoding="ascii")
        copied.extend(
            (
                self._artifact("update_feed", feed),
                self._artifact("update_feed_digest", feed_digest),
            )
        )

        manifest = bundle / self.MANIFEST_NAME
        manifest_payload = {
            "schema_version": 1,
            "release_id": initial.release_id,
            "version": self.version,
            "channel": initial.channel,
            "generated_at": self._now(),
            "rollout_percentage": initial.rollout_percentage,
            "source_distribution": str(initial.source_distribution),
            "signature_policy": {
                "required": require_signatures,
                "application_verified": signature_gates.get(
                    "application_signature", False
                ),
                "installer_verified": signature_gates.get(
                    "installer_signature", False
                ),
                "timestamp_verified": signature_gates.get(
                    "signature_timestamp", False
                ),
            },
            "artifacts": [item.to_dict() | {"path": item.path.name} for item in copied],
        }
        self._write_json(manifest, manifest_payload)
        copied.append(self._artifact("final_release_manifest", manifest))

        checksums = bundle / self.CHECKSUM_NAME
        checksums.write_text(
            "".join(f"{item.sha256}  {item.path.name}\n" for item in copied),
            encoding="ascii",
        )
        copied.append(self._artifact("final_release_checksums", checksums))

        manifest_ok, manifest_detail = self.verify_final_manifest(manifest)
        feed_ok, feed_detail = self.verify_update_feed(feed)
        if not manifest_ok:
            raise RuntimeError(manifest_detail)
        if not feed_ok:
            raise RuntimeError(feed_detail)

        status = "ready" if signatures_ready else "ready_with_warnings"
        final = replace(
            initial,
            bundle_dir=bundle,
            update_feed=feed,
            status=status,
            summary=(
                "Signed installer, signed application and update-channel package are verified."
                if status == "ready"
                else "Final release package is verified; Authenticode signing remains incomplete or portable-only."
            ),
            artifacts=tuple(copied),
        )
        self._write_json(bundle / self.RESULT_NAME, final.to_dict())
        self._publish_latest(bundle)
        self._publish_channel_feed(feed, initial.channel)
        return final

    def verify_final_manifest(self, manifest_path: Path) -> tuple[bool, str]:
        path = Path(manifest_path)
        try:
            payload = self._json(path)
            artifacts = payload.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                return False, "Final release manifest contains no artifacts."
            for item in artifacts:
                artifact = path.parent / Path(str(item["path"])).name
                if not artifact.exists():
                    return False, f"Final release artifact is missing: {artifact.name}"
                if self._sha256(artifact) != str(item["sha256"]):
                    return False, f"SHA-256 mismatch for final release artifact: {artifact.name}"
            return True, f"Final release manifest verified with {len(artifacts)} artifact(s)."
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"Final release verification failed: {exc}"

    def verify_update_feed(self, feed_path: Path) -> tuple[bool, str]:
        path = Path(feed_path)
        try:
            payload = self._json(path)
            channel = self.normalize_channel(str(payload["channel"]))
            if str(payload["version"]) != self.version:
                return False, "Update feed version does not match the current release."
            artifacts = payload.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                return False, "Update feed contains no downloadable artifacts."
            for item in artifacts:
                filename = Path(str(item["filename"])).name
                if str(item.get("url") or "") != filename:
                    return False, f"Update URL must be a safe relative filename: {filename}"
                artifact = path.parent / filename
                if not artifact.exists():
                    return False, f"Update artifact is missing: {filename}"
                if self._sha256(artifact) != str(item["sha256"]):
                    return False, f"SHA-256 mismatch for update artifact: {filename}"
            digest_path = (
                path.with_suffix(".sha256")
                if path.name == "latest.json"
                else path.parent / self.FEED_DIGEST_NAME
            )
            if not digest_path.exists():
                return False, "Update feed digest is missing."
            expected = digest_path.read_text(encoding="ascii").split()[0].casefold()
            if expected != self._sha256(path):
                return False, f"SHA-256 mismatch for update feed: {path.name}"
            return True, f"Update feed {channel} verified with {len(artifacts)} artifact(s)."
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"Update feed verification failed: {exc}"

    def export_snapshot(self, snapshot: FinalReleaseSnapshot | None = None) -> Path:
        current = snapshot or self.snapshot()
        folder = self.runtime.artifacts_dir / "final-release-readiness"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "final-release-readiness.json"
        self._write_json(path, current.to_dict())
        return path

    def _signing_evidence(self) -> list[SigningEvidence]:
        path = self.runtime.artifacts_dir / "package" / self.SIGNING_RESULT_NAME
        payload = self._json(path)
        records = payload.get("artifacts") if isinstance(payload, dict) else None
        evidence: list[SigningEvidence] = []
        if isinstance(records, list):
            for item in records:
                if not isinstance(item, dict):
                    continue
                raw_path = str(item.get("path") or "")
                evidence.append(
                    SigningEvidence(
                        role=str(item.get("role") or "unknown"),
                        path=Path(raw_path) if raw_path else None,
                        status=str(item.get("status") or "unavailable"),
                        sha256=str(item.get("sha256") or ""),
                        subject=str(item.get("subject") or ""),
                        thumbprint=str(item.get("thumbprint") or ""),
                        timestamped=bool(item.get("timestamped")),
                        detail=str(item.get("detail") or ""),
                    )
                )
        for role in ("application_executable", "windows_installer"):
            if not any(item.role == role for item in evidence):
                evidence.append(
                    SigningEvidence(
                        role=role,
                        path=None,
                        status="unavailable",
                        detail="No signing evidence was recorded for this artifact.",
                    )
                )
        return evidence

    def _listed_artifacts(self, source: Path, payload: dict[str, Any]) -> dict[str, Path]:
        result: dict[str, Path] = {}
        records = payload.get("artifacts")
        if not isinstance(records, list):
            return result
        for item in records:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            name = Path(str(item.get("path") or "")).name
            if role and name:
                result[role] = source / name
        return result

    def _privacy_audit(self, folder: Path) -> tuple[bool, str]:
        if not folder.exists():
            return False, "Distribution directory does not exist."
        forbidden_parts = {"credentials", "logs", "reports", "output", "s-talking-data"}
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            parts = {part.casefold() for part in path.relative_to(folder).parts}
            if parts & forbidden_parts or path.name.casefold() in self.SENSITIVE_NAMES:
                return False, f"Sensitive or writable data found in release input: {path.name}"
        return True, "No credentials, local settings, databases, logs, reports or generated outputs were found."

    def _evidence_integrity(self, evidence: SigningEvidence) -> bool:
        if evidence.path is None or not evidence.path.exists() or not evidence.sha256:
            return False
        try:
            return self._sha256(evidence.path) == evidence.sha256
        except OSError:
            return False

    @staticmethod
    def _signature(
        signatures: list[SigningEvidence] | tuple[SigningEvidence, ...], role: str
    ) -> SigningEvidence:
        return next(
            (item for item in signatures if item.role == role),
            SigningEvidence(role=role, path=None, status="unavailable"),
        )

    @classmethod
    def _signature_status(
        cls,
        role: str,
        signatures: list[SigningEvidence] | tuple[SigningEvidence, ...],
    ) -> str:
        mapped = {
            "windows_installer": "windows_installer",
            "portable_package": "application_executable",
        }.get(role)
        return cls._signature(signatures, mapped).status if mapped else "not_applicable"

    @staticmethod
    def _role_for_name(name: str) -> str:
        folded = name.casefold()
        if folded.endswith("-portable.zip"):
            return "portable_package"
        if folded.endswith("-setup.exe"):
            return "windows_installer"
        if folded == "release-notes.md":
            return "release_notes"
        if folded == "distribution-manifest.json":
            return "distribution_manifest"
        if folded == "sha256sums.txt":
            return "distribution_checksums"
        return Path(name).stem.replace("-", "_").casefold()

    @staticmethod
    def _is_pe(path: Path | None) -> bool:
        if path is None or not path.exists() or path.suffix.casefold() != ".exe":
            return False
        try:
            return path.stat().st_size >= 4096 and path.read_bytes()[:2] == b"MZ"
        except OSError:
            return False

    def _artifact(
        self,
        role: str,
        path: Path,
        signature_status: str = "not_applicable",
    ) -> FinalReleaseArtifact:
        return FinalReleaseArtifact(
            role=role,
            path=Path(path),
            size_bytes=Path(path).stat().st_size,
            sha256=self._sha256(path),
            signature_status=signature_status,
        )

    @staticmethod
    def _gate(
        code: str,
        label: str,
        passed: bool,
        severity: str,
        detail: str,
        remediation: str,
    ) -> FinalReleaseGate:
        return FinalReleaseGate(
            code=code,
            label=label,
            status="passed" if passed else "failed",
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _status(gates: list[FinalReleaseGate]) -> str:
        if any(item.severity == "blocker" and not item.passed for item in gates):
            return "blocked"
        if any(item.severity == "warning" and not item.passed for item in gates):
            return "ready_with_warnings"
        return "ready"

    @staticmethod
    def _summary(status: str, installer: bool, signed: bool) -> str:
        if status == "ready":
            return "Final signed release packaging and update-channel metadata are ready."
        if status == "ready_with_warnings":
            if not installer:
                return "Final portable release is ready; installer and signing remain optional warnings."
            if not signed:
                return "Final release artifacts are ready; Authenticode signing remains incomplete."
            return "Final release is ready with non-blocking warnings."
        return "Final release packaging is blocked by one or more mandatory gates."

    def _release_id(self, source: Path, channel: str) -> str:
        seed = f"{self.version}|{channel}|{source}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:16]

    @staticmethod
    def _rollout(value: int) -> int:
        rollout = int(value)
        if not 1 <= rollout <= 100:
            raise ValueError("Rollout percentage must be between 1 and 100.")
        return rollout

    def _publish_latest(self, bundle: Path) -> None:
        latest = self.latest_release_dir()
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(bundle, latest)

    def _publish_channel_feed(self, feed: Path, channel: str) -> None:
        target = self.latest_channel_feed(channel)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._json(feed)
        records = payload.get("artifacts") if isinstance(payload, dict) else None
        if isinstance(records, list):
            for item in records:
                if not isinstance(item, dict):
                    continue
                name = Path(str(item.get("filename") or "")).name
                source = feed.parent / name
                if name and source.exists():
                    shutil.copy2(source, target.parent / name)
        shutil.copy2(feed, target)
        digest = target.with_suffix(".sha256")
        digest.write_text(f"{self._sha256(target)}  {target.name}\n", encoding="ascii")

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        Path(path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
