from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

import app
from app.config.runtime import RuntimeConfig
from app.models.release_lifecycle_validation import (
    ReleaseLifecycleGate,
    ReleaseLifecycleSnapshot,
    ReleaseLifecycleSource,
)
from app.services.evidence_integrity import EvidenceIntegrityMixin
from app.services.final_release_service import FinalReleaseService
from app.services.stable_release_promotion_service import StableReleasePromotionService
from app.services.update_delivery_service import UpdateDeliveryService
from app.services.upgrade_recovery_service import UpgradeRecoveryService


class ReleaseLifecycleValidationService(EvidenceIntegrityMixin):
    """Validate release -> update -> migration -> recovery as one guarded chain."""

    SCHEMA_VERSION = 1
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|cookie|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(
        r"(?i)(?:[A-Z]:\\|/home/|/Users/|/tmp/|/var/|\\\\[^\\]+\\[^\\]+)"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        final_release_service: FinalReleaseService,
        update_delivery_service: UpdateDeliveryService,
        upgrade_recovery_service: UpgradeRecoveryService,
        stable_release_promotion_service: StableReleasePromotionService,
        *,
        version: str | None = None,
        channel: str = "stable",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.final_release_service = final_release_service
        self.update_delivery_service = update_delivery_service
        self.upgrade_recovery_service = upgrade_recovery_service
        self.stable_release_promotion_service = stable_release_promotion_service
        self.version = str(version or app.__version__)
        self.channel = FinalReleaseService.normalize_channel(channel)
        self.root = runtime.artifacts_dir / "release-lifecycle-validation"
        self.snapshot_root = self.root / "snapshots"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "automatic_download": False,
            "automatic_install": False,
            "automatic_restart": False,
            "automatic_restore": False,
            "automatic_rollback": False,
            "automatic_publish": False,
            "source_data_mutated": False,
            "private_data_included": False,
            "diagnostic_evidence_may_be_written": True,
        }

    def default_manifest_path(self) -> Path:
        return self.stable_release_promotion_service.default_final_manifest_path()

    def default_feed_path(self) -> Path:
        return self.stable_release_promotion_service.default_stable_feed_path()

    def default_promotion_receipt_path(self) -> Path:
        return (
            self.stable_release_promotion_service.root
            / self.stable_release_promotion_service.RECEIPT_NAME
        )

    def default_backup_dir(self) -> Path:
        return self.upgrade_recovery_service.latest_backup_dir()

    def assess(
        self,
        *,
        manifest_path: Path | None = None,
        feed_path: Path | None = None,
        promotion_receipt_path: Path | None = None,
        backup_dir: Path | None = None,
        source_version: str | None = None,
    ) -> ReleaseLifecycleSnapshot:
        manifest = Path(manifest_path or self.default_manifest_path())
        feed = Path(feed_path or self.default_feed_path())
        receipt = Path(promotion_receipt_path or self.default_promotion_receipt_path())
        backup = Path(backup_dir or self.default_backup_dir())
        source = str(source_version or self.version)

        gates: list[ReleaseLifecycleGate] = []
        sources: list[ReleaseLifecycleSource] = []

        manifest_ok, manifest_detail = self._verify_file(
            manifest,
            self.final_release_service.verify_final_manifest,
            "Final release manifest is missing.",
        )
        gates.append(
            self._gate(
                "final_manifest",
                "Verified final release manifest",
                manifest_ok,
                "blocker",
                manifest_detail,
                "Rebuild and verify the final release package before lifecycle validation.",
            )
        )
        self._append_source(sources, "final_manifest", "Final release manifest", manifest)

        feed_ok, feed_detail = self._verify_file(
            feed,
            self.final_release_service.verify_update_feed,
            "Stable update feed is missing.",
        )
        gates.append(
            self._gate(
                "stable_feed",
                "Verified stable update feed",
                feed_ok,
                "blocker",
                feed_detail,
                "Publish a locally verified stable feed with matching SHA-256 metadata.",
            )
        )
        self._append_source(sources, "stable_feed", "Stable update feed", feed)

        receipt_ok, receipt_detail = self._verify_file(
            receipt,
            self.stable_release_promotion_service.verify_promotion_receipt,
            "Stable promotion receipt is missing.",
        )
        gates.append(
            self._gate(
                "stable_promotion_receipt",
                "Stable promotion provenance",
                receipt_ok,
                "blocker",
                receipt_detail,
                "Verify the stable promotion receipt and its bound release artifacts.",
            )
        )
        self._append_source(
            sources,
            "stable_promotion_receipt",
            "Stable promotion receipt",
            receipt,
        )

        update_snapshot = None
        if feed_ok:
            try:
                update_snapshot = self.update_delivery_service.check_for_updates(
                    feed,
                    force=True,
                    channel_override=self.channel,
                )
                update_ok = update_snapshot.blocker_count == 0 and update_snapshot.status in {
                    "current",
                    "available",
                    "deferred",
                }
                update_detail = (
                    f"Update client accepted {update_snapshot.channel}/"
                    f"{update_snapshot.latest_version or self.version}: {update_snapshot.summary}"
                )
            except Exception as exc:
                update_ok = False
                update_detail = f"Update client compatibility check failed: {exc}"
        else:
            update_ok = False
            update_detail = (
                "Update client compatibility was not evaluated because the stable feed is invalid."
            )
        update_warn = bool(
            update_snapshot is not None
            and update_ok
            and update_snapshot.status == "deferred"
        )
        gates.append(
            self._gate_status(
                "update_client",
                "Update-client feed compatibility",
                "warn" if update_warn else "pass" if update_ok else "block",
                "warning" if update_warn else "blocker",
                update_detail,
                "Resolve Update Delivery channel, artifact or compatibility blockers.",
            )
        )

        selected_artifact = ""
        if update_snapshot is not None and update_snapshot.selected_artifact is not None:
            selected_artifact = update_snapshot.selected_artifact.filename
        artifact_ok = bool(
            update_snapshot and update_snapshot.selected_artifact and update_ok
        )
        gates.append(
            self._gate(
                "installer_handoff",
                "Manual installer/package handoff",
                artifact_ok,
                "blocker",
                (
                    f"Verified feed selects {selected_artifact}; download and launch remain manual."
                    if artifact_ok
                    else "No verified installer or portable package is selectable for manual handoff."
                ),
                "Publish a supported installer or portable ZIP in the stable feed.",
            )
        )

        backup_manifest = backup / self.upgrade_recovery_service.MANIFEST_NAME
        backup_ok = False
        backup_detail = "Verified pre-upgrade backup is missing."
        if backup.exists() and backup.is_dir():
            backup_ok, backup_detail = self.upgrade_recovery_service.verify_backup(backup)
        gates.append(
            self._gate(
                "verified_backup",
                "Verified recovery backup",
                backup_ok,
                "blocker",
                backup_detail,
                "Create and verify a pre-upgrade backup in Upgrade & Recovery.",
            )
        )
        if backup_ok:
            self._append_source(
                sources,
                "upgrade_backup",
                "Upgrade/recovery backup manifest",
                backup_manifest,
            )

        try:
            upgrade_snapshot = self.upgrade_recovery_service.snapshot(
                source_version=source,
                backup_dir=backup if backup_ok else None,
            )
            upgrade_ok = upgrade_snapshot.blocker_count == 0
            upgrade_warn = upgrade_ok and upgrade_snapshot.warning_count > 0
            upgrade_detail = upgrade_snapshot.summary
            current_schema = int(upgrade_snapshot.current_schema)
            target_schema = int(upgrade_snapshot.target_schema)
        except Exception as exc:
            upgrade_ok = False
            upgrade_warn = False
            upgrade_detail = f"Upgrade preflight failed: {exc}"
            current_schema = 0
            target_schema = int(
                getattr(self.upgrade_recovery_service, "target_schema", 0)
            )
        gates.append(
            self._gate_status(
                "upgrade_preflight",
                "Upgrade / rollback preflight",
                "warn" if upgrade_warn else "pass" if upgrade_ok else "block",
                "warning" if upgrade_warn else "blocker",
                upgrade_detail,
                "Resolve Upgrade & Recovery gates before installation or rollback.",
            )
        )

        try:
            migration = self.upgrade_recovery_service.validate_migration(
                source_version=source,
            )
            migration_ok = str(migration.get("status") or "") == "ready"
            migration_detail = str(
                migration.get("detail") or "Migration validation returned no detail."
            )
        except Exception as exc:
            migration_ok = False
            migration_detail = f"Disposable migration validation failed: {exc}"
        gates.append(
            self._gate(
                "disposable_migration",
                "Disposable database migration",
                migration_ok,
                "blocker",
                migration_detail,
                "Fix migration compatibility before handing the release to the installer.",
            )
        )

        rollback_ok = backup_ok and current_schema <= target_schema
        gates.append(
            self._gate(
                "rollback_recovery",
                "Rollback / recovery evidence",
                rollback_ok,
                "blocker",
                (
                    f"Backup is verified and schema {current_schema} is compatible with recovery target {target_schema}."
                    if rollback_ok
                    else "A verified compatible backup is required for controlled rollback or recovery."
                ),
                "Create a compatible backup and verify it before release handoff.",
            )
        )

        gates.append(
            self._gate(
                "manual_execution_contract",
                "Human-controlled installation and recovery",
                True,
                "blocker",
                "Validation does not download, install, restart, restore, roll back or publish automatically.",
            )
        )

        status = self._status(gates)
        summary = self._summary(status, gates)
        generated_at = self._now_iso()
        validation_id = self._payload_digest(
            {
                "generated_at": generated_at,
                "version": self.version,
                "channel": self.channel,
                "source_version": source,
                "status": status,
            }
        )[:20]
        return ReleaseLifecycleSnapshot(
            validation_id=validation_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            source_version=source,
            status=status,
            summary=summary,
            current_schema=current_schema,
            target_schema=target_schema,
            update_status=(
                update_snapshot.status if update_snapshot is not None else "unknown"
            ),
            update_artifact=selected_artifact,
            gates=tuple(gates),
            sources=tuple(sources),
        )

    def export_snapshot(self, snapshot: ReleaseLifecycleSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["safety_contract"] = self._safety_contract()
        payload["snapshot_sha256"] = self._payload_digest(payload)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        path = self.snapshot_root / f"release-lifecycle-validation-{stamp}.json"
        self._write_json(path, payload)
        self._write_json(
            self.root / "latest-release-lifecycle-validation.json",
            payload,
        )
        return path

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Release lifecycle snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Release lifecycle snapshot SHA-256 does not match."
        contract = payload.get("safety_contract")
        if not isinstance(contract, dict) or not self._verify_safety_contract(contract):
            return False, "Release lifecycle snapshot violates the safety contract."
        if self._contains_private_payload(payload):
            return False, "Release lifecycle snapshot contains private or local-path material."
        records = payload.get("sources")
        if not isinstance(records, list):
            return False, "Release lifecycle snapshot source evidence is invalid."
        for item in records:
            if not isinstance(item, dict):
                return False, "Release lifecycle snapshot contains an invalid source record."
            relative = str(item.get("relative_path") or "")
            if not self._safe_archive_name(relative):
                return False, "Release lifecycle source path is unsafe."
            source = self.runtime.artifacts_dir / PurePosixPath(relative)
            if not source.exists() or not source.is_file():
                return False, f"Release lifecycle source is missing: {Path(relative).name}"
            if self._sha256(source) != str(item.get("sha256") or ""):
                return False, f"Release lifecycle source custody changed: {source.name}"
        return True, (
            f"Release lifecycle snapshot verified with {len(records)} source artifact(s)."
        )

    def _append_source(
        self,
        sources: list[ReleaseLifecycleSource],
        role: str,
        label: str,
        path: Path,
    ) -> None:
        target = Path(path)
        if not target.exists() or not target.is_file():
            return
        try:
            relative = target.resolve().relative_to(self.runtime.artifacts_dir.resolve())
        except ValueError:
            return
        relative_text = relative.as_posix()
        if not self._safe_archive_name(relative_text):
            return
        sources.append(
            ReleaseLifecycleSource(
                role=role,
                label=label,
                relative_path=relative_text,
                sha256=self._sha256(target),
            )
        )

    @staticmethod
    def _verify_file(path: Path, verifier, missing_detail: str) -> tuple[bool, str]:
        target = Path(path)
        if not target.exists() or not target.is_file():
            return False, missing_detail
        try:
            return verifier(target)
        except Exception as exc:
            return False, f"Evidence verification failed: {exc}"

    @staticmethod
    def _gate(
        code: str,
        label: str,
        passed: bool,
        severity: str,
        detail: str,
        action: str = "",
    ) -> ReleaseLifecycleGate:
        return ReleaseLifecycleValidationService._gate_status(
            code,
            label,
            "pass" if passed else "block",
            severity,
            detail,
            action,
        )

    @staticmethod
    def _gate_status(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        action: str = "",
    ) -> ReleaseLifecycleGate:
        return ReleaseLifecycleGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            action=action,
        )

    @staticmethod
    def _status(gates: list[ReleaseLifecycleGate]) -> str:
        if any(item.status == "block" for item in gates):
            return "blocked"
        if any(item.status == "warn" for item in gates):
            return "ready_with_warnings"
        return "ready"

    @staticmethod
    def _summary(status: str, gates: list[ReleaseLifecycleGate]) -> str:
        blockers = sum(item.status == "block" for item in gates)
        warnings = sum(item.status == "warn" for item in gates)
        if status == "blocked":
            return (
                f"Release lifecycle validation is blocked by {blockers} mandatory gate(s)."
            )
        if status == "ready_with_warnings":
            return (
                f"Release lifecycle is ready with {warnings} warning(s) requiring review."
            )
        return "Installer, update, migration and recovery handoff are verified end to end."
