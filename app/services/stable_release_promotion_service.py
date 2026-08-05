from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.stable_release_promotion import (
    StablePromotionArtifact,
    StablePromotionGate,
    StablePromotionSnapshot,
)
from app.services.production_release_certification_service import (
    ProductionReleaseCertificationService,
)


class StableReleasePromotionService:
    """Guard and certify the explicit stable-release promotion workflow.

    This service never invokes Git tag, Git push, a network upload, an installer,
    or an update installation. It verifies the approved Phase 60 attestation,
    binds the stable source commit to that attested parent, creates a rollback
    point, verifies locally built release artifacts, and writes a tamper-evident
    promotion receipt for a separate human-controlled publication step.
    """

    SCHEMA_VERSION = 1
    RECEIPT_NAME = "stable-release-promotion-receipt.json"
    ROLLBACK_MANIFEST_NAME = "stable-release-rollback-manifest.json"
    _STABLE_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    _COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
    _SECRET_KEY_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|cookie|private[_-]?key)"
    )
    _TOKEN_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{12,}\b")

    def __init__(
        self,
        runtime: RuntimeConfig,
        production_service: ProductionReleaseCertificationService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.production_service = production_service or ProductionReleaseCertificationService(runtime)
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "stable-promotion"
        self.rollback_root = self.root / "rollback-points"
        self.receipt_root = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run
        self.root.mkdir(parents=True, exist_ok=True)
        self.rollback_root.mkdir(parents=True, exist_ok=True)
        self.receipt_root.mkdir(parents=True, exist_ok=True)

    def default_attestation_path(self) -> Path:
        return self.runtime.artifacts_dir / "production-certification" / "production-release-attestation.json"

    def default_final_manifest_path(self) -> Path:
        return self.runtime.artifacts_dir / "final-release" / "latest" / "final-release-manifest.json"

    def default_stable_feed_path(self) -> Path:
        return self.runtime.artifacts_dir / "update-channel" / "stable" / "latest.json"

    def default_sbom_path(self) -> Path:
        return (
            self.runtime.artifacts_dir
            / "security-supply-chain"
            / "sbom"
            / "S-Talking-SBOM.spdx.json"
        )

    def snapshot(
        self,
        *,
        attestation_path: Path | None = None,
        source_commit: str = "",
        parent_commit: str = "",
        working_tree_clean: bool | None = None,
        rollout_percentage: int = 100,
        include_artifact_gates: bool = False,
        final_manifest_path: Path | None = None,
        stable_feed_path: Path | None = None,
        sbom_path: Path | None = None,
        require_installer: bool = False,
        require_signatures: bool = False,
    ) -> StablePromotionSnapshot:
        attestation = Path(attestation_path or self.default_attestation_path())
        attestation_payload, attestation_ok, attestation_detail = self._attestation_payload(attestation)
        attested_commit = str(attestation_payload.get("source_commit") or "").strip()
        target_version = str(attestation_payload.get("target_version") or "").strip()
        current_commit = self._resolve_commit(source_commit)
        parent = self._resolve_parent_commit(parent_commit)
        clean = self._working_tree_clean() if working_tree_clean is None else bool(working_tree_clean)
        rollout = int(rollout_percentage)

        gates: list[StablePromotionGate] = []
        artifacts: list[StablePromotionArtifact] = []

        identity_ok = bool(self._STABLE_VERSION_RE.fullmatch(self.version)) and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Stable version and channel identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Application identity is {self.version} on stable."
                    if identity_ok
                    else f"Application identity must be stable X.Y.Z/stable, not {self.version}/{self.channel}."
                ),
                "Apply the reviewed stable-version promotion patch before building artifacts.",
            )
        )
        gates.append(
            self._gate(
                "production_attestation",
                "Verified production attestation",
                "pass" if attestation_ok else "block",
                "blocker",
                attestation_detail,
                "Regenerate and verify the Phase 60 production attestation.",
            )
        )
        target_ok = attestation_ok and target_version == self.version
        gates.append(
            self._gate(
                "attested_target",
                "Attested stable target",
                "pass" if target_ok else "block",
                "blocker",
                (
                    f"Attestation authorizes target {target_version}."
                    if target_ok
                    else f"Attestation target {target_version or 'missing'} does not match {self.version}."
                ),
                "Use the exact stable target authorized by the production attestation.",
            )
        )
        commit_ok = bool(self._COMMIT_RE.fullmatch(current_commit))
        gates.append(
            self._gate(
                "source_commit",
                "Committed stable source",
                "pass" if commit_ok else "block",
                "blocker",
                f"Stable source commit is {current_commit}." if commit_ok else "A valid stable source commit is unavailable.",
                "Commit the reviewed stable promotion patch before building release artifacts.",
            )
        )
        lineage_ok = (
            attestation_ok
            and bool(self._COMMIT_RE.fullmatch(attested_commit))
            and bool(self._COMMIT_RE.fullmatch(parent))
            and parent.casefold() == attested_commit.casefold()
        )
        gates.append(
            self._gate(
                "attested_lineage",
                "Attested commit is direct parent",
                "pass" if lineage_ok else "block",
                "blocker",
                (
                    f"Stable promotion commit directly follows attested commit {attested_commit}."
                    if lineage_ok
                    else (
                        f"Expected parent {attested_commit or 'missing'}, observed {parent or 'missing'}."
                    )
                ),
                "Rebase the stable version promotion directly onto the attested Phase 60 commit.",
            )
        )
        gates.append(
            self._gate(
                "clean_working_tree",
                "Clean working tree",
                "pass" if clean else "block",
                "blocker",
                "Working tree is clean." if clean else "Working tree contains uncommitted changes.",
                "Commit or discard local changes before release packaging.",
            )
        )
        packaging_ok, packaging_detail = self._packaging_identity()
        gates.append(
            self._gate(
                "packaging_identity",
                "Packaging version identity",
                "pass" if packaging_ok else "block",
                "blocker",
                packaging_detail,
                "Synchronize pyproject, Windows installer defaults and version metadata.",
            )
        )
        rollout_ok = 1 <= rollout <= 100
        gates.append(
            self._gate(
                "stable_rollout",
                "Stable staged rollout",
                "pass" if rollout_ok else "block",
                "blocker",
                f"Stable rollout is {rollout}%." if rollout_ok else "Rollout must be between 1 and 100 percent.",
                "Choose a stable rollout percentage from 1 to 100.",
            )
        )
        gates.append(
            self._gate(
                "manual_publication",
                "Human-controlled publication",
                "pass",
                "blocker",
                "No tag, push, upload, install, restart or stable-feed publication is performed automatically.",
            )
        )

        if attestation.exists() and attestation.is_file():
            artifacts.append(self._artifact("production_attestation", attestation))

        if include_artifact_gates:
            artifact_gates, verified_artifacts = self._stable_artifact_gates(
                final_manifest_path=Path(final_manifest_path or self.default_final_manifest_path()),
                stable_feed_path=Path(stable_feed_path or self.default_stable_feed_path()),
                sbom_path=Path(sbom_path or self.default_sbom_path()),
                rollout_percentage=rollout,
                require_installer=require_installer,
                require_signatures=require_signatures,
            )
            gates.extend(artifact_gates)
            artifacts.extend(verified_artifacts)

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        status = "blocked" if blockers else "ready_with_warnings" if warnings else "ready"
        summary = (
            f"Stable release promotion is blocked by {blockers} gate(s)."
            if blockers
            else f"Stable release promotion is ready with {warnings} warning(s)."
            if warnings
            else "Stable release promotion is ready for an explicit local build and human publication."
        )
        seed = f"{self.version}|{current_commit}|{attested_commit}|{self._now().date().isoformat()}"
        return StablePromotionSnapshot(
            promotion_id=hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20],
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            source_commit=current_commit,
            attested_commit=attested_commit,
            rollout_percentage=rollout,
            status=status,
            summary=summary,
            promotion_allowed=blockers == 0,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )

    def create_rollback_point(
        self,
        snapshot: StablePromotionSnapshot,
        *,
        attestation_path: Path | None = None,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        if not snapshot.promotion_allowed:
            return {
                "status": "blocked",
                "detail": "Rollback point cannot be prepared while promotion blockers remain.",
                "path": "",
            }
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "No rollback point was written. Explicit acknowledgement is required.",
                "path": "",
            }

        attestation = Path(attestation_path or self.default_attestation_path())
        payload, ok, detail = self._attestation_payload(attestation)
        if not ok:
            return {"status": "blocked", "detail": detail, "path": ""}
        if str(payload.get("target_version") or "") != self.version:
            return {
                "status": "blocked",
                "detail": "Attestation target no longer matches the stable application version.",
                "path": "",
            }

        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        folder = self.rollback_root / f"S-Talking-{self.version}-rollback-{stamp}"
        folder.mkdir(parents=True, exist_ok=False)
        copied: list[StablePromotionArtifact] = []
        copied_names: set[str] = set()

        def copy_artifact(role: str, source: Path) -> None:
            if not source.exists() or not source.is_file() or source.name in copied_names:
                return
            target = folder / source.name
            shutil.copy2(source, target)
            copied.append(self._artifact(role, target))
            copied_names.add(source.name)

        preview_dir = self.runtime.artifacts_dir / "update-channel" / "preview"
        preview_feed = preview_dir / "latest.json"
        for role, source in (
            ("production_attestation", attestation),
            ("stable_release_identity", self.runtime.app_root / "app" / "release.py"),
            ("preview_update_feed", preview_feed),
            ("preview_update_feed_digest", preview_dir / "latest.sha256"),
            ("upgrade_backup_manifest", self.runtime.artifacts_dir / "upgrade-recovery" / "latest" / "upgrade-backup-manifest.json"),
        ):
            copy_artifact(role, source)

        preview_payload = self._read_json(preview_feed) or {}
        preview_records = preview_payload.get("artifacts")
        if isinstance(preview_records, list):
            for item in preview_records:
                if not isinstance(item, Mapping):
                    continue
                filename = str(item.get("filename") or "")
                if self._safe_filename(filename):
                    copy_artifact("previous_release_artifact", preview_dir / filename)
        notes_name = str(preview_payload.get("release_notes_url") or "")
        if self._safe_filename(notes_name):
            copy_artifact("previous_release_notes", preview_dir / notes_name)

        previous_identity = folder / "previous-release-identity.json"
        self._write_json(
            previous_identity,
            {
                "source_version": str(payload.get("source_version") or ""),
                "target_version": str(payload.get("target_version") or ""),
                "source_commit": str(payload.get("source_commit") or ""),
                "release_channel": str(payload.get("release_channel") or "rc"),
            },
        )
        copied.append(self._artifact("previous_release_identity", previous_identity))

        manifest_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "rollback_id": uuid.uuid4().hex,
            "created_at": self._now_iso(),
            "stable_version": self.version,
            "stable_commit": snapshot.source_commit,
            "attested_commit": snapshot.attested_commit,
            "automatic_restore": False,
            "automatic_publish": False,
            "artifacts": [item.to_dict() for item in copied],
        }
        manifest_payload["manifest_sha256"] = self._payload_digest(manifest_payload)
        manifest = folder / self.ROLLBACK_MANIFEST_NAME
        self._write_json(manifest, manifest_payload)
        ok, detail = self.verify_rollback_manifest(manifest)
        if not ok:
            shutil.rmtree(folder, ignore_errors=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        latest = self.root / self.ROLLBACK_MANIFEST_NAME
        self._write_json(latest, manifest_payload)
        return {
            "status": "prepared",
            "detail": f"Verified rollback point contains {len(copied)} artifact(s).",
            "path": str(manifest),
        }

    def verify_rollback_manifest(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Rollback manifest is unreadable."
        expected = str(payload.get("manifest_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("manifest_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Rollback manifest SHA-256 does not match."
        records = payload.get("artifacts")
        if not isinstance(records, list) or not records:
            return False, "Rollback manifest contains no artifacts."
        for item in records:
            if not isinstance(item, Mapping):
                return False, "Rollback manifest contains an invalid artifact record."
            raw_name = str(item.get("path") or "")
            if not self._safe_filename(raw_name):
                return False, "Rollback artifact filename is unsafe."
            artifact = Path(path).parent / raw_name
            if not artifact.exists() or not artifact.is_file():
                return False, f"Rollback artifact is missing: {raw_name}"
            if artifact.stat().st_size != int(item.get("size_bytes") or -1):
                return False, f"Rollback artifact size mismatch: {raw_name}"
            if self._sha256(artifact) != str(item.get("sha256") or ""):
                return False, f"Rollback artifact SHA-256 mismatch: {raw_name}"
        return True, f"Rollback manifest verified with {len(records)} artifact(s)."

    def write_promotion_receipt(
        self,
        snapshot: StablePromotionSnapshot,
        *,
        rollback_manifest: Path,
        attestation_path: Path | None = None,
        final_manifest_path: Path | None = None,
        stable_feed_path: Path | None = None,
        sbom_path: Path | None = None,
        acknowledge: bool = False,
        require_installer: bool = False,
        require_signatures: bool = False,
    ) -> dict[str, object]:
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "No promotion receipt was written. Explicit acknowledgement is required.",
                "path": "",
            }
        if not snapshot.promotion_allowed:
            return {
                "status": "blocked",
                "detail": "Promotion receipt cannot be written while source gates remain blocked.",
                "path": "",
            }
        rollback_ok, rollback_detail = self.verify_rollback_manifest(Path(rollback_manifest))
        if not rollback_ok:
            return {"status": "blocked", "detail": rollback_detail, "path": ""}

        attestation = Path(attestation_path or self.default_attestation_path())
        final_snapshot = self.snapshot(
            attestation_path=attestation,
            source_commit=snapshot.source_commit,
            parent_commit=snapshot.attested_commit,
            working_tree_clean=True,
            rollout_percentage=snapshot.rollout_percentage,
            include_artifact_gates=True,
            final_manifest_path=final_manifest_path,
            stable_feed_path=stable_feed_path,
            sbom_path=sbom_path,
            require_installer=require_installer,
            require_signatures=require_signatures,
        )
        artifact_blockers = [
            gate for gate in final_snapshot.gates if gate.status == "block"
        ]
        if artifact_blockers:
            return {
                "status": "blocked",
                "detail": artifact_blockers[0].detail,
                "path": "",
            }

        final_manifest = Path(final_manifest_path or self.default_final_manifest_path())
        stable_feed = Path(stable_feed_path or self.default_stable_feed_path())
        sbom = Path(sbom_path or self.default_sbom_path())
        receipt_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "promotion_id": snapshot.promotion_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "source_commit": snapshot.source_commit,
            "attested_commit": snapshot.attested_commit,
            "rollout_percentage": snapshot.rollout_percentage,
            "status": final_snapshot.status,
            "warning_count": final_snapshot.warning_count,
            "manual_publish_required": True,
            "automatic_publish": False,
            "automatic_tag": False,
            "automatic_push": False,
            "automatic_install": False,
            "artifacts": [
                self._receipt_artifact("production_attestation", attestation),
                self._receipt_artifact("rollback_manifest", Path(rollback_manifest)),
                self._receipt_artifact("final_release_manifest", final_manifest),
                self._receipt_artifact("stable_update_feed", stable_feed),
                self._receipt_artifact("spdx_sbom", sbom),
            ],
        }
        receipt_payload["receipt_sha256"] = self._payload_digest(receipt_payload)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        receipt = self.receipt_root / f"stable-release-promotion-receipt-{stamp}.json"
        self._write_json(receipt, receipt_payload)
        ok, detail = self.verify_promotion_receipt(receipt)
        if not ok:
            receipt.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        self._write_json(self.root / self.RECEIPT_NAME, receipt_payload)
        return {"status": "verified", "detail": detail, "path": str(receipt)}

    def verify_promotion_receipt(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Stable promotion receipt is unreadable."
        expected = str(payload.get("receipt_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Stable promotion receipt SHA-256 does not match."
        if str(payload.get("version") or "") != self.version or str(payload.get("channel") or "") != "stable":
            return False, "Stable promotion receipt identity does not match the application."
        if payload.get("automatic_publish") is not False or payload.get("automatic_tag") is not False:
            return False, "Stable promotion receipt violates the manual-publication contract."
        records = payload.get("artifacts")
        if not isinstance(records, list) or len(records) < 5:
            return False, "Stable promotion receipt is missing required artifacts."
        for item in records:
            if not isinstance(item, Mapping):
                return False, "Stable promotion receipt contains an invalid artifact record."
            raw_path = str(item.get("path") or "")
            pure = Path(raw_path)
            if pure.is_absolute() or ".." in pure.parts:
                return False, "Receipt artifact path is unsafe."
            artifact = (self.runtime.app_root / pure).resolve()
            try:
                artifact.relative_to(self.runtime.app_root.resolve())
            except ValueError:
                return False, "Receipt artifact path escapes the application root."
            if not artifact.exists() or not artifact.is_file():
                return False, f"Receipt artifact is missing: {artifact.name or raw_path}"
            if artifact.stat().st_size != int(item.get("size_bytes") or -1):
                return False, f"Receipt artifact size mismatch: {artifact.name}"
            if self._sha256(artifact) != str(item.get("sha256") or ""):
                return False, f"Receipt artifact SHA-256 mismatch: {artifact.name}"
        return True, f"Stable promotion receipt verified with {len(records)} artifact(s)."

    def export_snapshot(self, snapshot: StablePromotionSnapshot) -> Path:
        path = self.root / "stable-release-promotion-summary.json"
        payload = snapshot.to_dict()
        payload["private_data_included"] = False
        payload["automatic_publish"] = False
        self._write_json(path, payload)
        return path

    def _stable_artifact_gates(
        self,
        *,
        final_manifest_path: Path,
        stable_feed_path: Path,
        sbom_path: Path,
        rollout_percentage: int,
        require_installer: bool,
        require_signatures: bool,
    ) -> tuple[list[StablePromotionGate], list[StablePromotionArtifact]]:
        gates: list[StablePromotionGate] = []
        artifacts: list[StablePromotionArtifact] = []

        manifest_ok, manifest_detail, manifest_payload = self._verify_final_manifest(final_manifest_path)
        gates.append(
            self._gate(
                "stable_final_manifest",
                "Stable final-release manifest",
                "pass" if manifest_ok else "block",
                "blocker",
                manifest_detail,
                "Build and verify the stable final-release bundle from this commit.",
            )
        )
        if manifest_ok:
            artifacts.append(self._artifact("final_release_manifest", final_manifest_path))

        feed_ok, feed_detail = self._verify_stable_feed(
            stable_feed_path, expected_rollout=rollout_percentage
        )
        gates.append(
            self._gate(
                "stable_update_feed",
                "Stable update feed",
                "pass" if feed_ok else "block",
                "blocker",
                feed_detail,
                "Build the stable channel feed and verify every downloadable artifact.",
            )
        )
        if feed_ok:
            artifacts.append(self._artifact("stable_update_feed", stable_feed_path))

        sbom_ok, sbom_detail = self._verify_sbom(sbom_path)
        gates.append(
            self._gate(
                "stable_sbom",
                "SPDX software bill of materials",
                "pass" if sbom_ok else "block",
                "blocker",
                sbom_detail,
                "Generate and verify the SPDX 2.3 SBOM from the stable build environment.",
            )
        )
        if sbom_ok:
            artifacts.append(self._artifact("spdx_sbom", sbom_path))

        records = manifest_payload.get("artifacts") if isinstance(manifest_payload, dict) else None
        roles = (
            {
                str(item.get("role") or "")
                for item in records
                if isinstance(item, Mapping)
            }
            if isinstance(records, list)
            else set()
        )
        installer_present = "windows_installer" in roles
        gates.append(
            self._gate(
                "stable_installer",
                "Windows installer artifact",
                "pass" if installer_present else "block" if require_installer else "warn",
                "blocker" if require_installer else "warning",
                "Compiled Windows installer is included." if installer_present else "Stable release remains portable-only because no compiled installer is included.",
                "Install Inno Setup, rebuild and include the canonical Windows installer." if not installer_present else "",
            )
        )

        signature_policy = manifest_payload.get("signature_policy") if isinstance(manifest_payload, dict) else None
        app_signed = bool(signature_policy.get("application_verified")) if isinstance(signature_policy, Mapping) else False
        installer_signed = bool(signature_policy.get("installer_verified")) if isinstance(signature_policy, Mapping) else False
        timestamped = bool(signature_policy.get("timestamp_verified")) if isinstance(signature_policy, Mapping) else False
        signatures_ok = app_signed and (installer_signed if installer_present else not require_installer) and timestamped
        gates.append(
            self._gate(
                "stable_signatures",
                "Authenticode and timestamp evidence",
                "pass" if signatures_ok else "block" if require_signatures else "warn",
                "blocker" if require_signatures else "warning",
                (
                    "Application and installer signatures include timestamp evidence."
                    if signatures_ok
                    else "Stable artifacts are verified by SHA-256, but complete timestamped Authenticode evidence is unavailable."
                ),
                "Configure SignTool, certificate thumbprint and timestamp URL, then rebuild." if not signatures_ok else "",
            )
        )
        return gates, artifacts

    def _attestation_payload(self, path: Path) -> tuple[dict[str, Any], bool, str]:
        if not path.exists() or not path.is_file():
            return {}, False, "Production attestation is missing."
        ok, detail = self.production_service.verify_attestation(path)
        document = self._read_json(path) or {}
        payload = document.get("payload") if isinstance(document.get("payload"), dict) else {}
        if self._contains_secret(payload):
            return {}, False, "Production attestation contains a secret-bearing field."
        return dict(payload), ok, detail

    def _verify_final_manifest(self, path: Path) -> tuple[bool, str, dict[str, Any]]:
        payload = self._read_json(path)
        if not isinstance(payload, dict):
            return False, "Stable final-release manifest is missing or unreadable.", {}
        if str(payload.get("version") or "") != self.version or str(payload.get("channel") or "") != "stable":
            return False, "Final-release manifest does not identify the current stable version.", payload
        records = payload.get("artifacts")
        if not isinstance(records, list) or not records:
            return False, "Final-release manifest contains no artifacts.", payload
        for item in records:
            if not isinstance(item, Mapping):
                return False, "Final-release manifest contains an invalid artifact record.", payload
            raw_name = str(item.get("path") or "")
            if not self._safe_filename(raw_name):
                return False, "Final-release artifact filename is unsafe.", payload
            artifact = path.parent / raw_name
            if not artifact.exists() or not artifact.is_file():
                return False, f"Final-release artifact is missing: {raw_name}", payload
            if self._sha256(artifact) != str(item.get("sha256") or ""):
                return False, f"Final-release artifact SHA-256 mismatch: {raw_name}", payload
        return True, f"Stable final-release manifest verified with {len(records)} artifact(s).", payload

    def _verify_stable_feed(
        self, path: Path, *, expected_rollout: int
    ) -> tuple[bool, str]:
        payload = self._read_json(path)
        if not isinstance(payload, dict):
            return False, "Stable update feed is missing or unreadable."
        if str(payload.get("product") or "") != "S Talking":
            return False, "Stable update feed product identity is invalid."
        if str(payload.get("channel") or "") != "stable" or str(payload.get("version") or "") != self.version:
            return False, "Stable update feed version or channel is invalid."
        if int(payload.get("rollout_percentage") or 0) != int(expected_rollout):
            return False, "Stable update feed rollout does not match the approved promotion rollout."
        records = payload.get("artifacts")
        if not isinstance(records, list) or not records:
            return False, "Stable update feed contains no downloadable artifacts."
        for item in records:
            if not isinstance(item, Mapping):
                return False, "Stable update feed contains an invalid artifact record."
            filename = str(item.get("filename") or "")
            if not self._safe_filename(filename) or str(item.get("url") or "") != filename:
                return False, "Stable update feed contains an unsafe artifact URL."
            artifact = path.parent / filename
            if not artifact.exists() or not artifact.is_file():
                return False, f"Stable update artifact is missing: {filename}"
            if artifact.stat().st_size != int(item.get("size_bytes") or -1):
                return False, f"Stable update artifact size mismatch: {filename}"
            if self._sha256(artifact) != str(item.get("sha256") or ""):
                return False, f"Stable update artifact SHA-256 mismatch: {filename}"
        digest = path.with_suffix(".sha256")
        if not digest.exists() or not digest.is_file():
            return False, "Stable update feed digest is missing."
        try:
            expected = digest.read_text(encoding="ascii").split()[0].casefold()
        except (OSError, IndexError):
            return False, "Stable update feed digest is unreadable."
        if expected != self._sha256(path):
            return False, "Stable update feed digest does not match."
        return True, f"Stable update feed verified with {len(records)} artifact(s)."

    def _verify_sbom(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if not isinstance(payload, dict) or payload.get("spdxVersion") != "SPDX-2.3":
            return False, "SPDX 2.3 SBOM is missing or unreadable."
        packages = payload.get("packages")
        if not isinstance(packages, list) or not packages:
            return False, "SPDX SBOM contains no packages."
        if self._contains_secret(payload):
            return False, "SPDX SBOM contains a secret-bearing field."
        serialized = json.dumps(payload, ensure_ascii=False)
        if str(self.runtime.app_root) in serialized or str(self.runtime.settings_path.parent) in serialized:
            return False, "SPDX SBOM contains a local filesystem path."
        identifiers = {
            str(item.get("SPDXID") or "")
            for item in packages
            if isinstance(item, Mapping)
        }
        if "SPDXRef-Package-S-Talking" not in identifiers:
            return False, "SPDX SBOM does not identify S Talking."
        app_package = next(
            (item for item in packages if isinstance(item, Mapping) and item.get("SPDXID") == "SPDXRef-Package-S-Talking"),
            {},
        )
        if str(app_package.get("versionInfo") or "") != self.version:
            return False, "SPDX SBOM application version does not match the stable release."
        return True, f"SPDX SBOM verified with {len(packages)} package(s)."

    def _packaging_identity(self) -> tuple[bool, str]:
        pyproject = self._read_text(self.runtime.app_root / "pyproject.toml")
        installer = self._read_text(self.runtime.app_root / "packaging" / "windows" / "S-Talking.iss")
        version_info = self._read_text(self.runtime.app_root / "packaging" / "windows" / "version_info.txt")
        normalized = self.version.replace("-", "")
        checks = (
            f'version = "{normalized}"' in pyproject,
            f'#define AppVersion "{self.version}"' in installer,
            f'#define OutputBaseFilename "S-Talking-{self.version}-setup"' in installer,
            f'StringStruct("FileVersion", "{self.version}")' in version_info,
            f'StringStruct("ProductVersion", "{self.version}")' in version_info,
        )
        if all(checks):
            return True, f"PyProject, installer and Windows metadata identify {self.version}."
        return False, "One or more packaging metadata files do not match the stable version."

    def _resolve_commit(self, explicit: str) -> str:
        value = str(explicit or "").strip()
        if value:
            return value
        return self._git_output(["rev-parse", "HEAD"])

    def _resolve_parent_commit(self, explicit: str) -> str:
        value = str(explicit or "").strip()
        if value:
            return value
        return self._git_output(["rev-parse", "HEAD^"])

    def _working_tree_clean(self) -> bool:
        try:
            completed = self._command_runner(
                ["git", "status", "--porcelain"],
                cwd=self.runtime.app_root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and str(completed.stdout or "").strip() == ""

    def _git_output(self, args: list[str]) -> str:
        try:
            completed = self._command_runner(
                ["git", *args],
                cwd=self.runtime.app_root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if completed.returncode != 0:
            return ""
        return str(completed.stdout or "").strip()

    @classmethod
    def _contains_secret(cls, value: object, *, key: str = "") -> bool:
        if (
            cls._SECRET_KEY_RE.fullmatch(key.strip())
            and not isinstance(value, (bool, int, float, type(None)))
            and value not in ("", [], {})
        ):
            return True
        if isinstance(value, Mapping):
            return any(cls._contains_secret(item, key=str(name)) for name, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(cls._contains_secret(item, key=key) for item in value)
        if isinstance(value, str):
            return bool(cls._TOKEN_RE.search(value))
        return False

    @staticmethod
    def _safe_filename(value: str) -> bool:
        if not value or "/" in value or "\\" in value:
            return False
        path = Path(value)
        return path.name == value and not path.is_absolute() and ".." not in path.parts

    def _artifact(self, role: str, path: Path, *, status: str = "verified", detail: str = "") -> StablePromotionArtifact:
        return StablePromotionArtifact(
            role=role,
            path=Path(path),
            size_bytes=Path(path).stat().st_size,
            sha256=self._sha256(Path(path)),
            status=status,
            detail=detail,
        )

    def _receipt_artifact(self, role: str, path: Path) -> dict[str, object]:
        resolved = Path(path).resolve()
        relative = resolved.relative_to(self.runtime.app_root.resolve())
        return {
            "role": role,
            "path": relative.as_posix(),
            "size_bytes": resolved.stat().st_size,
            "sha256": self._sha256(resolved),
        }

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> StablePromotionGate:
        return StablePromotionGate(code, label, status, severity, detail, remediation)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return Path(path).read_text(encoding="utf-8-sig")
        except OSError:
            return ""

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _payload_digest(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _now(self) -> datetime:
        return self._now_provider().astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat().replace("+00:00", "Z")
