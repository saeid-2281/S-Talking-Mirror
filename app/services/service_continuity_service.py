from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.service_continuity import (
    ServiceContinuityBackupSource,
    ServiceContinuityDrillRecord,
    ServiceContinuityGate,
    ServiceContinuityRenewalSource,
    ServiceContinuitySnapshot,
)
from app.services.reliability_assurance_renewal_service import (
    ReliabilityAssuranceRenewalService,
)
from app.services.upgrade_recovery_service import UpgradeRecoveryService


class ServiceContinuityService:
    """Govern non-destructive continuity drills from verified recovery evidence.

    Phase 70 consumes intact Phase 69 renewal triplets and verified upgrade backup
    directories. It creates a human-controlled drill plan and records measured RTO,
    RPO, database integrity and regression evidence. It never restores, deletes,
    restarts, deploys, uploads, publishes or changes production data automatically.
    """

    SCHEMA_VERSION = 1
    DEFAULT_RTO_MINUTES = 60
    MIN_RTO_MINUTES = 1
    MAX_RTO_MINUTES = 10080
    DEFAULT_RPO_MINUTES = 1440
    MIN_RPO_MINUTES = 0
    MAX_RPO_MINUTES = 43200
    DEFAULT_DRILL_WINDOW_DAYS = 90
    MIN_DRILL_WINDOW_DAYS = 1
    MAX_DRILL_WINDOW_DAYS = 3650
    ENVIRONMENTS = (
        "isolated_sandbox",
        "staging_clone",
        "offline_validation",
    )
    RENEWAL_DECISIONS = (
        "renew",
        "renew_with_follow_up",
        "withhold_renewal",
    )
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )
    _ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,127}$")

    def __init__(
        self,
        runtime: RuntimeConfig,
        reliability_renewal_service: ReliabilityAssuranceRenewalService,
        upgrade_recovery_service: UpgradeRecoveryService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.reliability_renewal_service = reliability_renewal_service
        self.upgrade_recovery_service = upgrade_recovery_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "service-continuity"
        self.snapshots_dir = self.root / "snapshots"
        self.plans_dir = self.root / "plans"
        self.results_dir = self.root / "results"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.plans_dir,
            self.results_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_renewal_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_renewal_service.renewals_dir.glob("renewal-*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_follow_up_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_renewal_service.follow_up_dir.glob(
                    "renewal-*-follow-up.json"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_audit_pack_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_renewal_service.audit_packs_dir.glob(
                    "renewal-*-audit-pack.zip"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_receipt_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_renewal_service.receipts_dir.glob(
                    "renewal-*-receipt.json"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_backup_dirs(self) -> tuple[Path, ...]:
        root = Path(self.upgrade_recovery_service.root)
        if not root.is_dir():
            return ()
        candidates: dict[str, Path] = {}
        manifest_name = str(self.upgrade_recovery_service.MANIFEST_NAME)
        for path in root.iterdir():
            if not path.is_dir() or not (path / manifest_name).is_file():
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            candidates[key] = path
        return tuple(sorted(candidates.values(), key=lambda path: path.stat().st_mtime))

    def snapshot(
        self,
        *,
        renewal_paths: Iterable[Path] = (),
        follow_up_paths: Iterable[Path] = (),
        audit_pack_paths: Iterable[Path] = (),
        receipt_paths: Iterable[Path] = (),
        backup_dirs: Iterable[Path] = (),
        rto_target_minutes: int = DEFAULT_RTO_MINUTES,
        rpo_target_minutes: int = DEFAULT_RPO_MINUTES,
        drill_window_days: int = DEFAULT_DRILL_WINDOW_DAYS,
    ) -> ServiceContinuitySnapshot:
        renewals = tuple(dict.fromkeys(Path(path) for path in renewal_paths))
        follow_ups = tuple(dict.fromkeys(Path(path) for path in follow_up_paths))
        packs = tuple(dict.fromkeys(Path(path) for path in audit_pack_paths))
        receipts = tuple(dict.fromkeys(Path(path) for path in receipt_paths))
        backups = tuple(dict.fromkeys(Path(path) for path in backup_dirs))
        if not renewals:
            renewals = self.default_renewal_paths()
        if not follow_ups:
            follow_ups = self.default_follow_up_paths()
        if not packs:
            packs = self.default_audit_pack_paths()
        if not receipts:
            receipts = self.default_receipt_paths()
        if not backups:
            backups = self.default_backup_dirs()

        rto = self._bounded_int(
            rto_target_minutes,
            self.MIN_RTO_MINUTES,
            self.MAX_RTO_MINUTES,
            self.DEFAULT_RTO_MINUTES,
        )
        rpo = self._bounded_int(
            rpo_target_minutes,
            self.MIN_RPO_MINUTES,
            self.MAX_RPO_MINUTES,
            self.DEFAULT_RPO_MINUTES,
        )
        window = self._bounded_int(
            drill_window_days,
            self.MIN_DRILL_WINDOW_DAYS,
            self.MAX_DRILL_WINDOW_DAYS,
            self.DEFAULT_DRILL_WINDOW_DAYS,
        )
        generated_at = self._now_iso()
        snapshot_id = (
            f"continuity-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        gates: list[ServiceContinuityGate] = []

        identity_ok = self.version == app.__version__ and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Stable application identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Stable identity verified: {self.version} ({self.channel})."
                    if identity_ok
                    else f"Expected {app.__version__} on stable; found {self.version} ({self.channel})."
                ),
                "Run continuity governance from the certified stable application.",
            )
        )

        target_ok = (
            self.MIN_RTO_MINUTES <= int(rto_target_minutes) <= self.MAX_RTO_MINUTES
            and self.MIN_RPO_MINUTES <= int(rpo_target_minutes) <= self.MAX_RPO_MINUTES
            and self.MIN_DRILL_WINDOW_DAYS
            <= int(drill_window_days)
            <= self.MAX_DRILL_WINDOW_DAYS
        )
        gates.append(
            self._gate(
                "recovery_objectives",
                "Recovery objective policy",
                "pass" if target_ok else "block",
                "blocker",
                f"RTO {rto} min, RPO {rpo} min, evidence window {window} day(s).",
                "Use supported RTO, RPO and drill-window values.",
            )
        )

        renewal_sources, renewal_rejected = self._renewal_sources(
            renewals, follow_ups, packs, receipts
        )
        active_renewals = tuple(
            source for source in renewal_sources if source.decision != "withhold_renewal"
        )
        withheld_count = len(renewal_sources) - len(active_renewals)
        open_follow_up_count = sum(
            source.follow_up_status == "open" for source in active_renewals
        )
        renewal_counts_match = (
            len(renewals) == len(follow_ups) == len(packs) == len(receipts)
        )
        renewal_ok = bool(active_renewals) and renewal_rejected == 0 and renewal_counts_match
        gates.append(
            self._gate(
                "renewal_custody",
                "Phase 69 renewal custody",
                "pass" if renewal_ok else "block",
                "blocker",
                (
                    f"Verified {len(active_renewals)} active renewal triplet(s)."
                    if renewal_ok
                    else (
                        "An intact one-to-one renewal, follow-up, audit-pack and receipt set is required. "
                        f"Selected {len(renewals)}/{len(follow_ups)}/{len(packs)}/{len(receipts)}; "
                        f"rejected {renewal_rejected}; withheld {withheld_count}."
                    )
                ),
                "Select matching verified Phase 69 artifacts and resolve withheld renewal decisions.",
            )
        )
        if open_follow_up_count:
            gates.append(
                self._gate(
                    "renewal_follow_up",
                    "Renewal follow-up",
                    "warn",
                    "warning",
                    f"{open_follow_up_count} active renewal source(s) carry open follow-up.",
                    "Keep the follow-up owner and review date visible during the drill.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "renewal_follow_up",
                    "Renewal follow-up",
                    "pass",
                    "warning",
                    "No active renewal source carries open follow-up.",
                )
            )

        backup_sources, backup_rejected = self._backup_sources(backups, window)
        stale_count = sum(source.status == "stale" for source in backup_sources)
        backup_ok = bool(backup_sources) and backup_rejected == 0
        gates.append(
            self._gate(
                "verified_backup",
                "Verified recovery backup",
                "pass" if backup_ok else "block",
                "blocker",
                (
                    f"Verified {len(backup_sources)} recovery backup(s)."
                    if backup_ok
                    else f"No complete verified recovery backup is available; rejected {backup_rejected}."
                ),
                "Create and verify a fresh upgrade-recovery backup before planning a drill.",
            )
        )
        if stale_count:
            gates.append(
                self._gate(
                    "backup_freshness",
                    "Backup freshness",
                    "warn",
                    "warning",
                    f"{stale_count} verified backup(s) are older than {window} day(s).",
                    "Create a newer verified backup or explicitly retain the stale-evidence warning.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "backup_freshness",
                    "Backup freshness",
                    "pass",
                    "warning",
                    f"All verified backups are within the {window}-day evidence window.",
                )
            )

        gates.append(
            self._gate(
                "non_destructive_contract",
                "Non-destructive continuity contract",
                "pass",
                "blocker",
                "Planning and evidence recording do not restore, delete, restart, deploy, upload or publish anything automatically.",
            )
        )

        status = self._status(gates)
        drill_allowed = status != "blocked" and bool(active_renewals) and bool(backup_sources)
        summary = self._summary(status, len(active_renewals), len(backup_sources))
        return ServiceContinuitySnapshot(
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            rto_target_minutes=rto,
            rpo_target_minutes=rpo,
            drill_window_days=window,
            status=status,
            status_summary=summary,
            drill_allowed=drill_allowed,
            selected_renewal_count=len(renewals),
            selected_follow_up_count=len(follow_ups),
            selected_pack_count=len(packs),
            selected_receipt_count=len(receipts),
            selected_backup_count=len(backups),
            verified_renewal_count=len(active_renewals),
            verified_backup_count=len(backup_sources),
            stale_backup_count=stale_count,
            open_follow_up_count=open_follow_up_count,
            withheld_renewal_count=withheld_count,
            rejected_source_count=renewal_rejected + backup_rejected,
            renewals=tuple(active_renewals),
            backups=tuple(backup_sources),
            gates=tuple(gates),
        )

    def create_drill_plan(
        self,
        snapshot: ServiceContinuitySnapshot,
        *,
        owner: str,
        environment: str,
        notes: str,
        acknowledge: bool = False,
    ) -> ServiceContinuityDrillRecord | dict[str, object]:
        if snapshot.blocker_count or not snapshot.drill_allowed:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review renewal custody, backup evidence and recovery objectives before creating a drill plan.",
                "path": "",
            }
        normalized_owner = self._clean_text(owner, minimum=3, maximum=120)
        normalized_notes = self._clean_text(notes, minimum=24, maximum=1600)
        normalized_environment = str(environment or "").strip().lower()
        if normalized_owner is None or normalized_notes is None:
            return {
                "status": "blocked",
                "detail": "A privacy-safe human owner and drill statement are required.",
                "path": "",
            }
        if normalized_environment not in self.ENVIRONMENTS:
            return {"status": "blocked", "detail": "Drill environment is unsupported.", "path": ""}

        refreshed = self.snapshot(
            renewal_paths=(source.renewal_path for source in snapshot.renewals),
            follow_up_paths=(source.follow_up_path for source in snapshot.renewals),
            audit_pack_paths=(source.audit_pack_path for source in snapshot.renewals),
            receipt_paths=(source.receipt_path for source in snapshot.renewals),
            backup_dirs=(source.backup_dir for source in snapshot.backups),
            rto_target_minutes=snapshot.rto_target_minutes,
            rpo_target_minutes=snapshot.rpo_target_minutes,
            drill_window_days=snapshot.drill_window_days,
        )
        if refreshed.blocker_count:
            return {"status": "blocked", "detail": refreshed.status_summary, "path": ""}
        if {item.renewal_id for item in refreshed.renewals} != {
            item.renewal_id for item in snapshot.renewals
        } or {item.backup_id for item in refreshed.backups} != {
            item.backup_id for item in snapshot.backups
        }:
            return {
                "status": "blocked",
                "detail": "Continuity source identity changed after the snapshot.",
                "path": "",
            }

        drill_id = f"continuity-drill-{uuid.uuid4().hex[:12]}"
        created_at = self._now_iso()
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "snapshot_id": refreshed.snapshot_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "planned",
            "owner": normalized_owner,
            "environment": normalized_environment,
            "notes": normalized_notes,
            "rto_target_minutes": refreshed.rto_target_minutes,
            "rpo_target_minutes": refreshed.rpo_target_minutes,
            "drill_window_days": refreshed.drill_window_days,
            "renewal_sources": [self._renewal_record(item) for item in refreshed.renewals],
            "backup_sources": [self._backup_record(item) for item in refreshed.backups],
            "steps": self._drill_steps(),
            "human_plan_reviewed": True,
            **self._safety_contract(),
        }
        payload["plan_sha256"] = self._payload_digest(payload)
        plan_path = self.plans_dir / f"{drill_id}-plan.json"
        self._write_json(plan_path, payload)
        ok, detail = self.verify_plan(plan_path)
        if not ok:
            plan_path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        self._write_json(self.root / "latest-continuity-plan.json", payload)
        return ServiceContinuityDrillRecord(
            drill_id=drill_id,
            created_at=created_at,
            outcome="pending",
            plan_path=plan_path,
        )

    def record_drill_result(
        self,
        plan_path: Path,
        *,
        actual_restore_minutes: int,
        observed_data_loss_minutes: int,
        database_quick_check: str,
        manifest_verified: bool,
        regression_test_count: int,
        failed_test_count: int,
        owner: str,
        conclusion: str,
        acknowledge: bool = False,
    ) -> ServiceContinuityDrillRecord | dict[str, object]:
        plan_path = Path(plan_path)
        plan_ok, plan_detail = self.verify_plan(plan_path)
        if not plan_ok:
            return {"status": "blocked", "detail": plan_detail, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review measured recovery evidence before recording the drill result.",
                "path": "",
            }
        owner_value = self._clean_text(owner, minimum=3, maximum=120)
        conclusion_value = self._clean_text(conclusion, minimum=24, maximum=1600)
        if owner_value is None or conclusion_value is None:
            return {
                "status": "blocked",
                "detail": "A privacy-safe human result owner and conclusion are required.",
                "path": "",
            }
        restore_minutes = self._safe_int(actual_restore_minutes, -1)
        data_loss_minutes = self._safe_int(observed_data_loss_minutes, -1)
        tests = self._safe_int(regression_test_count, -1)
        failures = self._safe_int(failed_test_count, -1)
        if not 0 <= restore_minutes <= self.MAX_RTO_MINUTES:
            return {"status": "blocked", "detail": "Actual restore duration is invalid.", "path": ""}
        if not 0 <= data_loss_minutes <= self.MAX_RPO_MINUTES:
            return {"status": "blocked", "detail": "Observed data loss is invalid.", "path": ""}
        if tests < 1 or failures < 0 or failures > tests:
            return {"status": "blocked", "detail": "Regression test evidence is invalid.", "path": ""}
        quick_check = str(database_quick_check or "").strip().lower()
        if quick_check not in {"ok", "failed", "not_applicable"}:
            return {"status": "blocked", "detail": "Database quick_check evidence is invalid.", "path": ""}

        plan = self._read_json(plan_path) or {}
        rto_target = self._safe_int(plan.get("rto_target_minutes"), self.DEFAULT_RTO_MINUTES)
        rpo_target = self._safe_int(plan.get("rpo_target_minutes"), self.DEFAULT_RPO_MINUTES)
        database_required = any(
            bool(item.get("database_included"))
            for item in plan.get("backup_sources", [])
            if isinstance(item, Mapping)
        )
        database_ok = quick_check == "ok" if database_required else quick_check in {
            "ok",
            "not_applicable",
        }
        objective_met = restore_minutes <= rto_target and data_loss_minutes <= rpo_target
        evidence_met = bool(manifest_verified) and database_ok and failures == 0
        outcome = "passed" if objective_met and evidence_met else "failed"
        drill_id = str(plan.get("drill_id") or "")
        created_at = self._now_iso()
        result_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "outcome": outcome,
            "owner": owner_value,
            "conclusion": conclusion_value,
            "plan_filename": plan_path.name,
            "plan_sha256": self._sha256(plan_path),
            "rto_target_minutes": rto_target,
            "rpo_target_minutes": rpo_target,
            "actual_restore_minutes": restore_minutes,
            "observed_data_loss_minutes": data_loss_minutes,
            "database_quick_check": quick_check,
            "manifest_verified": bool(manifest_verified),
            "regression_test_count": tests,
            "failed_test_count": failures,
            "objective_met": objective_met,
            "evidence_met": evidence_met,
            "human_result_reviewed": True,
            **self._safety_contract(),
        }
        result_payload["result_sha256"] = self._payload_digest(result_payload)
        result_path = self.results_dir / f"{drill_id}-result.json"
        self._write_json(result_path, result_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "attestation_id": f"continuity-attestation-{uuid.uuid4().hex[:12]}",
            "drill_id": drill_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "verified" if outcome == "passed" else "withheld",
            "outcome": outcome,
            "owner": owner_value,
            "statement": conclusion_value,
            "plan_filename": plan_path.name,
            "plan_sha256": self._sha256(plan_path),
            "result_filename": result_path.name,
            "result_sha256": self._sha256(result_path),
            "rto_met": restore_minutes <= rto_target,
            "rpo_met": data_loss_minutes <= rpo_target,
            "integrity_met": evidence_met,
            "human_attestation_completed": True,
            **self._safety_contract(),
        }
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = self.attestations_dir / f"{drill_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_audit_pack(
            drill_id=drill_id,
            plan_path=plan_path,
            result_path=result_path,
            attestation_path=attestation_path,
        )
        result_ok, result_detail = self.verify_result(result_path)
        attestation_ok, attestation_detail = self.verify_attestation(attestation_path)
        pack_ok, pack_detail = self.verify_audit_pack(pack_path, receipt_path)
        if not result_ok or not attestation_ok or not pack_ok:
            for path in (result_path, attestation_path, pack_path, receipt_path):
                path.unlink(missing_ok=True)
            detail = (
                result_detail
                if not result_ok
                else attestation_detail
                if not attestation_ok
                else pack_detail
            )
            return {"status": "blocked", "detail": detail, "path": ""}

        self._write_json(self.root / "latest-continuity-result.json", result_payload)
        return ServiceContinuityDrillRecord(
            drill_id=drill_id,
            created_at=created_at,
            outcome=outcome,
            plan_path=plan_path,
            result_path=result_path,
            attestation_path=attestation_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
            status="verified",
        )

    def verify_plan(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Continuity drill plan is unreadable."
        expected = str(payload.get("plan_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("plan_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity drill plan SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "planned" or payload.get("human_plan_reviewed") is not True:
            return False, "Continuity drill plan lacks human acknowledgement."
        if str(payload.get("environment") or "") not in self.ENVIRONMENTS:
            return False, "Continuity drill environment is invalid."
        for field in ("owner", "notes"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "Continuity drill plan contains private material."
        renewals = payload.get("renewal_sources")
        backups = payload.get("backup_sources")
        if not isinstance(renewals, list) or not renewals:
            return False, "Continuity drill plan has no renewal custody."
        if not isinstance(backups, list) or not backups:
            return False, "Continuity drill plan has no backup custody."
        for record in renewals:
            ok, detail = self._verify_renewal_record(record)
            if not ok:
                return False, detail
        for record in backups:
            ok, detail = self._verify_backup_record(record)
            if not ok:
                return False, detail
        steps = payload.get("steps")
        if not isinstance(steps, list) or len(steps) < 6:
            return False, "Continuity drill plan steps are incomplete."
        if any(bool(step.get("automatic")) for step in steps if isinstance(step, Mapping)):
            return False, "Continuity drill plan contains an automatic operation."
        return True, "Continuity drill plan is intact and source verified."

    def verify_result(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Continuity drill result is unreadable."
        expected = str(payload.get("result_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("result_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity drill result SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get("human_result_reviewed") is not True:
            return False, "Continuity drill result lacks human review."
        if str(payload.get("outcome") or "") not in {"passed", "failed"}:
            return False, "Continuity drill outcome is invalid."
        for field in ("owner", "conclusion"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "Continuity drill result contains private material."
        plan_path = self.plans_dir / str(payload.get("plan_filename") or "")
        if not plan_path.is_file() or self._sha256(plan_path) != str(
            payload.get("plan_sha256") or ""
        ):
            return False, "Continuity drill plan custody changed."
        plan_ok, plan_detail = self.verify_plan(plan_path)
        if not plan_ok:
            return False, plan_detail
        plan = self._read_json(plan_path) or {}
        database_required = any(
            bool(item.get("database_included"))
            for item in plan.get("backup_sources", [])
            if isinstance(item, Mapping)
        )
        rto_target = self._safe_int(payload.get("rto_target_minutes"), -1)
        rpo_target = self._safe_int(payload.get("rpo_target_minutes"), -1)
        actual = self._safe_int(payload.get("actual_restore_minutes"), -1)
        loss = self._safe_int(payload.get("observed_data_loss_minutes"), -1)
        tests = self._safe_int(payload.get("regression_test_count"), -1)
        failures = self._safe_int(payload.get("failed_test_count"), -1)
        objective_met = actual <= rto_target and loss <= rpo_target
        quick_check = str(payload.get("database_quick_check") or "")
        database_evidence = (
            quick_check == "ok"
            if database_required
            else quick_check in {"ok", "not_applicable"}
        )
        evidence_met = (
            bool(payload.get("manifest_verified"))
            and database_evidence
            and tests > 0
            and failures == 0
        )
        expected_outcome = "passed" if objective_met and evidence_met else "failed"
        if bool(payload.get("objective_met")) != objective_met:
            return False, "Continuity objective result is inconsistent."
        if bool(payload.get("evidence_met")) != evidence_met:
            return False, "Continuity evidence result is inconsistent."
        if str(payload.get("outcome") or "") != expected_outcome:
            return False, "Continuity drill outcome was recalculated differently."
        return True, "Continuity drill result is intact and plan verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Continuity attestation is unreadable."
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity attestation SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("human_attestation_completed") is not True:
            return False, "Continuity attestation lacks human acknowledgement."
        if str(payload.get("status") or "") not in {"verified", "withheld"}:
            return False, "Continuity attestation status is invalid."
        for field in ("owner", "statement"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "Continuity attestation contains private material."
        result_path = self.results_dir / str(payload.get("result_filename") or "")
        if not result_path.is_file() or self._sha256(result_path) != str(
            payload.get("result_sha256") or ""
        ):
            return False, "Continuity result custody changed."
        result_ok, result_detail = self.verify_result(result_path)
        if not result_ok:
            return False, result_detail
        result = self._read_json(result_path) or {}
        expected_status = "verified" if result.get("outcome") == "passed" else "withheld"
        if str(payload.get("status") or "") != expected_status:
            return False, "Continuity attestation status does not match the drill result."
        return True, "Continuity attestation is intact and result verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Continuity audit-pack receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity receipt SHA-256 does not match."
        if not pack_path.is_file():
            return False, "Continuity audit pack is missing."
        if str(receipt.get("pack_filename") or "") != pack_path.name:
            return False, "Continuity audit-pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "Continuity audit-pack size changed."
        if str(receipt.get("pack_sha256") or "") != self._sha256(pack_path):
            return False, "Continuity audit-pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Continuity audit pack contains an unsafe path."
                required = {
                    "manifest.json",
                    "continuity/plan.json",
                    "continuity/result.json",
                    "continuity/attestation.json",
                }
                if not required.issubset(names):
                    return False, "Continuity audit pack is incomplete."
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                plan = json.loads(archive.read("continuity/plan.json").decode("utf-8"))
                result = json.loads(archive.read("continuity/result.json").decode("utf-8"))
                attestation = json.loads(
                    archive.read("continuity/attestation.json").decode("utf-8")
                )
                if not all(
                    isinstance(item, dict)
                    for item in (manifest, plan, result, attestation)
                ):
                    return False, "Continuity audit-pack JSON is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "Continuity manifest SHA-256 does not match."
                entries = manifest.get("entries")
                if not isinstance(entries, list):
                    return False, "Continuity manifest entries are invalid."
                for record in entries:
                    if not isinstance(record, Mapping):
                        return False, "Continuity manifest entry is invalid."
                    name = str(record.get("path") or "")
                    if name == "manifest.json" or name not in names:
                        return False, "Continuity manifest references an invalid entry."
                    data = archive.read(name)
                    if self._safe_int(record.get("size_bytes"), -1) != len(data):
                        return False, f"Continuity entry size changed: {name}"
                    if str(record.get("sha256") or "") != hashlib.sha256(data).hexdigest():
                        return False, f"Continuity entry SHA-256 changed: {name}"
        except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, KeyError):
            return False, "Continuity audit pack is unreadable."

        plan_ok, plan_detail = self._verify_plan_payload(plan)
        if not plan_ok:
            return False, plan_detail
        result_ok, result_detail = self._verify_result_payload(result)
        if not result_ok:
            return False, result_detail
        attestation_ok, attestation_detail = self._verify_attestation_payload(attestation)
        if not attestation_ok:
            return False, attestation_detail
        drill_id = str(plan.get("drill_id") or "")
        if str(result.get("drill_id") or "") != drill_id or str(
            attestation.get("drill_id") or ""
        ) != drill_id:
            return False, "Continuity audit-pack identities do not match."
        if str(receipt.get("drill_id") or "") != drill_id:
            return False, "Continuity receipt identity does not match."
        return True, "Continuity audit pack is intact and evidence verified."

    def export_snapshot(self, snapshot: ServiceContinuitySnapshot) -> Path:
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        payload = snapshot.to_dict()
        payload.update(self._safety_contract())
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["snapshot_sha256"] = self._payload_digest(payload)
        self._write_json(path, payload)
        return path

    def _renewal_sources(
        self,
        renewal_paths: tuple[Path, ...],
        follow_up_paths: tuple[Path, ...],
        audit_pack_paths: tuple[Path, ...],
        receipt_paths: tuple[Path, ...],
    ) -> tuple[list[ServiceContinuityRenewalSource], int]:
        renewals = self._index_json(renewal_paths, "renewal_id")
        follow_ups = self._index_json(follow_up_paths, "renewal_id")
        receipts = self._index_json(receipt_paths, "renewal_id")
        packs = {self._pack_renewal_id(path): path for path in audit_pack_paths}
        identities = set(renewals) | set(follow_ups) | set(receipts) | set(packs)
        sources: list[ServiceContinuityRenewalSource] = []
        rejected = 0
        for renewal_id in sorted(identities):
            renewal_item = renewals.get(renewal_id)
            follow_up_item = follow_ups.get(renewal_id)
            receipt_item = receipts.get(renewal_id)
            pack_path = packs.get(renewal_id)
            if not renewal_item or not follow_up_item or not receipt_item or pack_path is None:
                rejected += 1
                continue
            renewal_path, renewal = renewal_item
            follow_up_path, follow_up = follow_up_item
            receipt_path, _receipt = receipt_item
            if not self.reliability_renewal_service.verify_renewal(renewal_path)[0]:
                rejected += 1
                continue
            if not self.reliability_renewal_service.verify_follow_up(follow_up_path)[0]:
                rejected += 1
                continue
            if not self.reliability_renewal_service.verify_audit_pack(
                pack_path, receipt_path
            )[0]:
                rejected += 1
                continue
            decision = str(renewal.get("decision") or "")
            follow_up_status = str(follow_up.get("status") or "")
            if decision not in self.RENEWAL_DECISIONS or follow_up_status not in {
                "open",
                "not_required",
            }:
                rejected += 1
                continue
            sources.append(
                ServiceContinuityRenewalSource(
                    renewal_id=renewal_id,
                    decision=decision,
                    created_at=str(renewal.get("created_at") or ""),
                    follow_up_status=follow_up_status,
                    renewal_path=renewal_path,
                    follow_up_path=follow_up_path,
                    audit_pack_path=pack_path,
                    receipt_path=receipt_path,
                    renewal_sha256=self._sha256(renewal_path),
                    follow_up_sha256=self._sha256(follow_up_path),
                    audit_pack_sha256=self._sha256(pack_path),
                    receipt_sha256=self._sha256(receipt_path),
                )
            )
        return sources, rejected

    def _backup_sources(
        self, backup_dirs: tuple[Path, ...], window_days: int
    ) -> tuple[list[ServiceContinuityBackupSource], int]:
        sources: list[ServiceContinuityBackupSource] = []
        rejected = 0
        seen: set[str] = set()
        manifest_name = str(self.upgrade_recovery_service.MANIFEST_NAME)
        for backup_dir in backup_dirs:
            backup = Path(backup_dir)
            try:
                key = str(backup.resolve())
            except OSError:
                key = str(backup)
            if key in seen:
                rejected += 1
                continue
            seen.add(key)
            ok, _detail = self.upgrade_recovery_service.verify_backup(backup)
            manifest_path = backup / manifest_name
            manifest = self._read_json(manifest_path)
            if not ok or not isinstance(manifest, dict):
                rejected += 1
                continue
            backup_id = str(manifest.get("backup_id") or backup.name)
            if not self._ID_RE.fullmatch(backup_id):
                backup_id = re.sub(r"[^a-z0-9_.-]+", "-", backup.name.casefold()).strip("-")
            files = manifest.get("files")
            if not isinstance(files, list) or not files:
                rejected += 1
                continue
            created_at = str(manifest.get("created_at") or "")
            created = self._parse_datetime(created_at)
            if created is None:
                rejected += 1
                continue
            age_days = max(0, (self._now() - created).days)
            database_included = any(
                isinstance(item, Mapping)
                and str(item.get("role") or "") in {"database", "legacy_database"}
                for item in files
            )
            sources.append(
                ServiceContinuityBackupSource(
                    backup_id=backup_id or f"backup-{uuid.uuid4().hex[:8]}",
                    backup_name=backup.name,
                    created_at=created_at,
                    age_days=age_days,
                    file_count=len(files),
                    database_included=database_included,
                    backup_dir=backup,
                    manifest_path=manifest_path,
                    manifest_sha256=self._sha256(manifest_path),
                    status="fresh" if age_days <= window_days else "stale",
                )
            )
        return sources, rejected

    def _create_audit_pack(
        self,
        *,
        drill_id: str,
        plan_path: Path,
        result_path: Path,
        attestation_path: Path,
    ) -> tuple[Path, Path]:
        pack_path = self.audit_packs_dir / f"{drill_id}-audit-pack.zip"
        receipt_path = self.receipts_dir / f"{drill_id}-receipt.json"
        entries: dict[str, bytes] = {
            "continuity/plan.json": plan_path.read_bytes(),
            "continuity/result.json": result_path.read_bytes(),
            "continuity/attestation.json": attestation_path.read_bytes(),
        }
        manifest_entries = [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(entries.items())
        ]
        manifest: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "entries": manifest_entries,
            **self._safety_contract(),
        }
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        entries["manifest.json"] = self._json_bytes(manifest)
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
            "entry_count": len(entries),
            **self._safety_contract(),
        }
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _verify_renewal_record(self, record: object) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Continuity renewal source record is invalid."
        renewal_id = str(record.get("renewal_id") or "")
        if not self._ID_RE.fullmatch(renewal_id):
            return False, "Continuity renewal source identity is invalid."
        items = (
            ("renewal_filename", "renewal_sha256", self.reliability_renewal_service.renewals_dir, self.reliability_renewal_service.verify_renewal),
            ("follow_up_filename", "follow_up_sha256", self.reliability_renewal_service.follow_up_dir, self.reliability_renewal_service.verify_follow_up),
        )
        for filename_field, digest_field, root, verifier in items:
            filename = str(record.get(filename_field) or "")
            path = root / filename
            if not self._safe_filename(filename) or not path.is_file():
                return False, "Continuity renewal source file is missing."
            if self._sha256(path) != str(record.get(digest_field) or ""):
                return False, "Continuity renewal source SHA-256 changed."
            ok, detail = verifier(path)
            if not ok:
                return False, detail
        pack_filename = str(record.get("audit_pack_filename") or "")
        receipt_filename = str(record.get("receipt_filename") or "")
        pack_path = self.reliability_renewal_service.audit_packs_dir / pack_filename
        receipt_path = self.reliability_renewal_service.receipts_dir / receipt_filename
        if not self._safe_filename(pack_filename) or not self._safe_filename(receipt_filename):
            return False, "Continuity renewal audit-pack path is invalid."
        if not pack_path.is_file() or not receipt_path.is_file():
            return False, "Continuity renewal audit-pack custody is missing."
        if self._sha256(pack_path) != str(record.get("audit_pack_sha256") or ""):
            return False, "Continuity renewal audit-pack SHA-256 changed."
        if self._sha256(receipt_path) != str(record.get("receipt_sha256") or ""):
            return False, "Continuity renewal receipt SHA-256 changed."
        ok, detail = self.reliability_renewal_service.verify_audit_pack(pack_path, receipt_path)
        if not ok:
            return False, detail
        return True, "Continuity renewal source is intact."

    def _verify_backup_record(self, record: object) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Continuity backup source record is invalid."
        backup_name = str(record.get("backup_name") or "")
        if not self._safe_filename(backup_name):
            return False, "Continuity backup source name is invalid."
        backup_dir = Path(self.upgrade_recovery_service.root) / backup_name
        manifest_path = backup_dir / str(self.upgrade_recovery_service.MANIFEST_NAME)
        if not manifest_path.is_file():
            return False, "Continuity backup manifest is missing."
        if self._sha256(manifest_path) != str(record.get("manifest_sha256") or ""):
            return False, "Continuity backup manifest SHA-256 changed."
        ok, detail = self.upgrade_recovery_service.verify_backup(backup_dir)
        if not ok:
            return False, detail
        return True, "Continuity backup source is intact."

    def _renewal_record(self, source: ServiceContinuityRenewalSource) -> dict[str, object]:
        return {
            "renewal_id": source.renewal_id,
            "decision": source.decision,
            "follow_up_status": source.follow_up_status,
            "renewal_filename": source.renewal_path.name,
            "renewal_sha256": source.renewal_sha256,
            "follow_up_filename": source.follow_up_path.name,
            "follow_up_sha256": source.follow_up_sha256,
            "audit_pack_filename": source.audit_pack_path.name,
            "audit_pack_sha256": source.audit_pack_sha256,
            "receipt_filename": source.receipt_path.name,
            "receipt_sha256": source.receipt_sha256,
        }

    @staticmethod
    def _backup_record(source: ServiceContinuityBackupSource) -> dict[str, object]:
        return {
            "backup_id": source.backup_id,
            "backup_name": source.backup_name,
            "created_at": source.created_at,
            "age_days": source.age_days,
            "file_count": source.file_count,
            "database_included": source.database_included,
            "manifest_filename": source.manifest_path.name,
            "manifest_sha256": source.manifest_sha256,
            "status": source.status,
        }

    @staticmethod
    def _drill_steps() -> list[dict[str, object]]:
        return [
            {"order": 1, "action": "Prepare an isolated non-production recovery workspace.", "automatic": False},
            {"order": 2, "action": "Re-verify the selected backup manifest and every payload hash.", "automatic": False},
            {"order": 3, "action": "Copy the backup payload into the isolated workspace without changing production data.", "automatic": False},
            {"order": 4, "action": "Open the restored database and run SQLite quick_check when a database is present.", "automatic": False},
            {"order": 5, "action": "Run dedicated recovery checks and the approved regression suite.", "automatic": False},
            {"order": 6, "action": "Measure restore duration and the newest recoverable data point against RTO and RPO.", "automatic": False},
            {"order": 7, "action": "Record the human conclusion and retain local tamper-evident evidence.", "automatic": False},
        ]

    def _verify_plan_payload(self, payload: Mapping[str, Any]) -> tuple[bool, str]:
        expected = str(payload.get("plan_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("plan_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity audit-pack plan SHA-256 does not match."
        return self._verify_common_contract(payload)

    def _verify_result_payload(self, payload: Mapping[str, Any]) -> tuple[bool, str]:
        expected = str(payload.get("result_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("result_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity audit-pack result SHA-256 does not match."
        return self._verify_common_contract(payload)

    def _verify_attestation_payload(self, payload: Mapping[str, Any]) -> tuple[bool, str]:
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Continuity audit-pack attestation SHA-256 does not match."
        return self._verify_common_contract(payload)

    def _verify_common_contract(self, payload: Mapping[str, object]) -> tuple[bool, str]:
        if self._safe_int(payload.get("schema_version"), 0) != self.SCHEMA_VERSION:
            return False, "Continuity evidence schema is unsupported."
        if str(payload.get("version") or "") != self.version or str(
            payload.get("channel") or ""
        ) != self.channel:
            return False, "Continuity evidence application identity changed."
        for key, expected in self._safety_contract().items():
            if payload.get(key) is not expected:
                return False, f"Continuity safety contract changed: {key}"
        return True, "Continuity common contract is intact."

    @staticmethod
    def _safety_contract() -> dict[str, object]:
        return {
            "automatic_restore": False,
            "automatic_delete": False,
            "automatic_restart": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_upload": False,
            "automatic_publish": False,
            "production_data_modified": False,
            "private_data_included": False,
        }

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> ServiceContinuityGate:
        return ServiceContinuityGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _status(gates: Iterable[ServiceContinuityGate]) -> str:
        items = tuple(gates)
        if any(gate.status == "block" for gate in items):
            return "blocked"
        if any(gate.status == "warn" for gate in items):
            return "ready_with_follow_up"
        return "ready"

    @staticmethod
    def _summary(status: str, renewal_count: int, backup_count: int) -> str:
        if status == "blocked":
            return "Continuity drill planning is blocked until source custody and recovery evidence are complete."
        if status == "ready_with_follow_up":
            return f"Continuity drill is ready with governed follow-up using {renewal_count} renewal source(s) and {backup_count} verified backup(s)."
        return f"Continuity drill is ready using {renewal_count} renewal source(s) and {backup_count} verified backup(s)."

    def _index_json(
        self, paths: Iterable[Path], identity_field: str
    ) -> dict[str, tuple[Path, dict[str, Any]]]:
        result: dict[str, tuple[Path, dict[str, Any]]] = {}
        duplicates: set[str] = set()
        for path in paths:
            payload = self._read_json(path)
            identity = str((payload or {}).get(identity_field) or "")
            if not identity or identity in result:
                if identity:
                    duplicates.add(identity)
                continue
            result[identity] = (Path(path), payload or {})
        for identity in duplicates:
            result.pop(identity, None)
        return result

    @staticmethod
    def _pack_renewal_id(path: Path) -> str:
        name = Path(path).name
        suffix = "-audit-pack.zip"
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        pure = PurePosixPath(name)
        return bool(name) and not pure.is_absolute() and ".." not in pure.parts

    @staticmethod
    def _safe_filename(name: str) -> bool:
        return bool(name) and Path(name).name == name and name not in {".", ".."}

    def _clean_text(
        self,
        value: str,
        *,
        minimum: int,
        maximum: int,
        allow_empty: bool = False,
    ) -> str | None:
        text = " ".join(str(value or "").split()).strip()
        if not text and allow_empty:
            return ""
        if not minimum <= len(text) <= maximum:
            return None
        if self._contains_private_material(text):
            return None
        return text

    def _contains_private_material(self, value: str) -> bool:
        return bool(self._WINDOWS_PATH_RE.search(value) or self._SECRET_RE.search(value))

    @classmethod
    def _payload_digest(cls, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(cls._json_bytes(payload)).hexdigest()

    @staticmethod
    def _json_bytes(payload: Mapping[str, object]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        parsed = ServiceContinuityService._safe_int(value, default)
        return min(max(parsed, minimum), maximum)

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
