from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.reliability_assurance import (
    ReliabilityAssuranceException,
    ReliabilityAssuranceGate,
    ReliabilityAssuranceRecord,
    ReliabilityAssuranceSnapshot,
    ReliabilityAssuranceSource,
)
from app.services.prevention_effectiveness_service import PreventionEffectivenessService


class ReliabilityAssuranceService:
    """Create privacy-safe reliability assurance records and local audit packs.

    Phase 68 consumes only verified Phase 67 review/decision pairs. It never edits
    predecessor evidence and never publishes, uploads, schedules, creates tickets,
    accepts risk, deploys, rolls back, restarts or closes external work.
    """

    SCHEMA_VERSION = 1
    DEFAULT_ASSURANCE_WINDOW_DAYS = 90
    MIN_ASSURANCE_WINDOW_DAYS = 7
    MAX_ASSURANCE_WINDOW_DAYS = 3650
    MONITORING_REVIEW_DAYS = 30
    ASSURANCE_DECISIONS = (
        "assure",
        "assure_with_exceptions",
        "withhold_assurance",
    )
    SOURCE_DECISIONS = (
        "continue_monitoring",
        "escalate_prevention",
        "accept_residual_risk",
        "close_effective",
    )
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )
    _ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,127}$")

    def __init__(
        self,
        runtime: RuntimeConfig,
        prevention_effectiveness_service: PreventionEffectivenessService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.prevention_effectiveness_service = (
            prevention_effectiveness_service or PreventionEffectivenessService(runtime)
        )
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "reliability-assurance"
        self.snapshots_dir = self.root / "snapshots"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_review_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.prevention_effectiveness_service.reviews_dir.glob("review-*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_decision_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.prevention_effectiveness_service.decisions_dir.glob(
                    "review-*-decision.json"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def snapshot(
        self,
        *,
        review_paths: Iterable[Path] = (),
        decision_paths: Iterable[Path] = (),
        assurance_window_days: int = DEFAULT_ASSURANCE_WINDOW_DAYS,
    ) -> ReliabilityAssuranceSnapshot:
        reviews = tuple(dict.fromkeys(Path(path) for path in review_paths))
        decisions = tuple(dict.fromkeys(Path(path) for path in decision_paths))
        if not reviews:
            reviews = self.default_review_paths()
        if not decisions:
            decisions = self.default_decision_paths()

        generated_at = self._now_iso()
        snapshot_id = (
            f"assurance-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        gates: list[ReliabilityAssuranceGate] = []

        identity_ok = self.version == app.__version__ and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Stable application identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Running identity is {self.version}/{self.channel}."
                    if identity_ok
                    else "Reliability assurance requires the current stable identity."
                ),
                "Run this workflow from the verified stable build.",
            )
        )

        window_ok = (
            self.MIN_ASSURANCE_WINDOW_DAYS
            <= int(assurance_window_days)
            <= self.MAX_ASSURANCE_WINDOW_DAYS
        )
        gates.append(
            self._gate(
                "assurance_window",
                "Assurance review window",
                "pass" if window_ok else "block",
                "blocker",
                (
                    f"Assurance window is {assurance_window_days} day(s)."
                    if window_ok
                    else "Assurance window is outside the supported 7-3650 day range."
                ),
                "Choose an assurance window between 7 and 3650 days.",
            )
        )

        review_payloads: dict[str, tuple[Path, dict[str, Any]]] = {}
        decision_payloads: dict[str, tuple[Path, dict[str, Any]]] = {}
        rejected = 0

        for path in reviews:
            ok, _detail = self.prevention_effectiveness_service.verify_review(path)
            payload = self._read_json(path)
            review_id = str((payload or {}).get("review_id") or "")
            if not ok or not payload or not self._ID_RE.fullmatch(review_id):
                rejected += 1
                continue
            if review_id in review_payloads:
                rejected += 1
                continue
            review_payloads[review_id] = (path, payload)

        for path in decisions:
            ok, _detail = self.prevention_effectiveness_service.verify_decision(path)
            payload = self._read_json(path)
            review_id = str((payload or {}).get("review_id") or "")
            if not ok or not payload or not self._ID_RE.fullmatch(review_id):
                rejected += 1
                continue
            if review_id in decision_payloads:
                rejected += 1
                continue
            decision_payloads[review_id] = (path, payload)

        unpaired = set(review_payloads).symmetric_difference(decision_payloads)
        rejected += len(unpaired)
        paired_ids = sorted(set(review_payloads).intersection(decision_payloads))

        gates.append(
            self._gate(
                "phase67_custody",
                "Phase 67 review and decision custody",
                "block" if rejected else "pass",
                "blocker",
                (
                    f"Verified {len(paired_ids)} review/decision pair(s)."
                    if not rejected
                    else f"Rejected {rejected} invalid, duplicate or unpaired source item(s)."
                ),
                "Select intact one-to-one Phase 67 review and decision pairs.",
            )
        )

        sources: list[ReliabilityAssuranceSource] = []
        ignored = 0
        if window_ok:
            for review_id in paired_ids:
                review_path, review = review_payloads[review_id]
                decision_path, decision = decision_payloads[review_id]
                created_at = self._parse_datetime(str(decision.get("created_at") or ""))
                if created_at is None:
                    rejected += 1
                    continue
                age_days = max(0, int((self._now() - created_at).total_seconds() // 86400))
                if age_days > int(assurance_window_days):
                    ignored += 1
                    continue
                source_decision = str(decision.get("decision") or "")
                if source_decision not in self.SOURCE_DECISIONS:
                    rejected += 1
                    continue
                metrics = review.get("metrics")
                if not isinstance(metrics, Mapping):
                    rejected += 1
                    continue
                sources.append(
                    ReliabilityAssuranceSource(
                        review_id=review_id,
                        decision_id=str(decision.get("decision_id") or ""),
                        baseline_id=str(review.get("baseline_id") or ""),
                        decision=source_decision,
                        created_at=created_at.isoformat(),
                        age_days=age_days,
                        review_path=review_path,
                        decision_path=decision_path,
                        review_sha256=self._sha256(review_path),
                        decision_sha256=self._sha256(decision_path),
                        open_action_count=self._safe_int(metrics.get("open_action_count")),
                        overdue_action_count=self._safe_int(metrics.get("overdue_action_count")),
                        recurrent_pattern_count=self._safe_int(
                            metrics.get("recurrent_pattern_count")
                        ),
                        ineffective_pattern_count=self._safe_int(
                            metrics.get("ineffective_pattern_count")
                        ),
                    )
                )

        coverage_ok = bool(sources)
        gates.append(
            self._gate(
                "assurance_coverage",
                "Reliability assurance coverage",
                "pass" if coverage_ok else "block",
                "blocker",
                (
                    f"Included {len(sources)} verified pair(s); ignored {ignored} outside the window."
                    if coverage_ok
                    else "No verified Phase 67 pair is inside the assurance window."
                ),
                "Select a wider window or create a current Phase 67 effectiveness review.",
            )
        )

        exceptions = self._exceptions(sources)
        high_exceptions = sum(item.severity in {"high", "critical"} for item in exceptions)
        gates.append(
            self._gate(
                "exception_governance",
                "Open reliability exceptions",
                "warn" if exceptions else "pass",
                "warning",
                (
                    f"Found {len(exceptions)} open exception(s), including {high_exceptions} high/critical."
                    if exceptions
                    else "No open reliability exception requires governance."
                ),
                "Assign a human owner and next review date for every open exception.",
            )
        )

        gates.append(
            self._gate(
                "privacy_contract",
                "Privacy-safe assurance evidence",
                "pass",
                "blocker",
                "Audit records contain identifiers, categorical metrics, hashes and approved summaries only.",
            )
        )
        gates.append(
            self._gate(
                "manual_operations",
                "Human-controlled assurance",
                "pass",
                "blocker",
                "No ticket, schedule, risk acceptance, upload, publication, patch, deploy, rollback or restart is automatic.",
            )
        )

        # A late source-shape failure must remain a blocker even when initial custody passed.
        if rejected and not any(gate.code == "phase67_custody" and gate.status == "block" for gate in gates):
            gates.append(
                self._gate(
                    "source_shape",
                    "Phase 67 source structure",
                    "block",
                    "blocker",
                    f"Rejected {rejected} source item(s) while constructing assurance coverage.",
                    "Recreate invalid Phase 67 records and rerun the assurance review.",
                )
            )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            summary = f"Reliability assurance is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_exceptions"
            summary = (
                f"Reliability assurance is ready with {len(exceptions)} governed exception(s)."
            )
        else:
            status = "ready"
            summary = "Reliability assurance is ready without open exceptions."

        return ReliabilityAssuranceSnapshot(
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            assurance_window_days=int(assurance_window_days),
            status=status,
            status_summary=summary,
            assurance_allowed=blocker_count == 0,
            selected_review_count=len(reviews),
            selected_decision_count=len(decisions),
            verified_pair_count=len(sources),
            rejected_source_count=rejected,
            ignored_pair_count=ignored,
            close_effective_count=sum(source.decision == "close_effective" for source in sources),
            monitoring_count=sum(source.decision == "continue_monitoring" for source in sources),
            escalation_count=sum(source.decision == "escalate_prevention" for source in sources),
            accepted_risk_count=sum(source.decision == "accept_residual_risk" for source in sources),
            open_exception_count=len(exceptions),
            high_exception_count=high_exceptions,
            sources=tuple(sources),
            exceptions=tuple(exceptions),
            gates=tuple(gates),
        )

    def create_assurance(
        self,
        snapshot: ReliabilityAssuranceSnapshot,
        *,
        decision: str,
        owner: str,
        statement: str,
        exception_owner: str = "",
        next_review_date: str = "",
        acknowledge: bool = False,
    ) -> ReliabilityAssuranceRecord | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review every source, exception and assurance statement before creating an audit pack.",
                "path": "",
            }

        normalized_decision = str(decision or "").strip().lower()
        normalized_owner = self._clean_text(owner, minimum=3, maximum=120)
        normalized_statement = self._clean_text(statement, minimum=24, maximum=1200)
        normalized_exception_owner = self._clean_text(
            exception_owner, minimum=0, maximum=120, allow_empty=True
        )
        normalized_next_review = str(next_review_date or "").strip()
        if normalized_decision not in self.ASSURANCE_DECISIONS:
            return {"status": "blocked", "detail": "Assurance decision is unsupported.", "path": ""}
        if normalized_owner is None or normalized_statement is None:
            return {
                "status": "blocked",
                "detail": "A privacy-safe human owner and assurance statement are required.",
                "path": "",
            }
        if normalized_exception_owner is None:
            return {
                "status": "blocked",
                "detail": "Exception owner contains a secret or local absolute path.",
                "path": "",
            }

        gate_detail = self._decision_gate(
            snapshot,
            normalized_decision,
            normalized_exception_owner,
            normalized_next_review,
        )
        if gate_detail:
            return {"status": "blocked", "detail": gate_detail, "path": ""}

        refreshed = self.snapshot(
            review_paths=(source.review_path for source in snapshot.sources),
            decision_paths=(source.decision_path for source in snapshot.sources),
            assurance_window_days=snapshot.assurance_window_days,
        )
        if refreshed.blocker_count:
            return {"status": "blocked", "detail": refreshed.status_summary, "path": ""}
        if {source.review_id for source in refreshed.sources} != {
            source.review_id for source in snapshot.sources
        }:
            return {
                "status": "blocked",
                "detail": "Phase 67 source identity changed after the assurance snapshot.",
                "path": "",
            }

        assurance_id = f"assurance-{uuid.uuid4().hex[:12]}"
        created_at = self._now_iso()
        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "assurance_id": assurance_id,
            "snapshot_id": refreshed.snapshot_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "decision": normalized_decision,
            "owner": normalized_owner,
            "statement": normalized_statement,
            "exception_owner": normalized_exception_owner,
            "next_review_date": normalized_next_review,
            "assurance_window_days": refreshed.assurance_window_days,
            "metrics": {
                "verified_pair_count": refreshed.verified_pair_count,
                "close_effective_count": refreshed.close_effective_count,
                "monitoring_count": refreshed.monitoring_count,
                "escalation_count": refreshed.escalation_count,
                "accepted_risk_count": refreshed.accepted_risk_count,
                "open_exception_count": refreshed.open_exception_count,
                "high_exception_count": refreshed.high_exception_count,
            },
            "sources": [self._source_record(source) for source in refreshed.sources],
            "exceptions": [item.to_dict() for item in refreshed.exceptions],
            "human_assurance_completed": True,
            "human_exception_ownership": bool(normalized_exception_owner),
            "external_ticket_updated": False,
            "schedule_updated": False,
            "risk_register_updated": False,
            "automatic_risk_acceptance": False,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_upload": False,
            "automatic_publish": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "private_data_included": False,
        }
        attestation_payload["attestation_sha256"] = self._payload_digest(attestation_payload)
        attestation_path = self.attestations_dir / f"{assurance_id}.json"
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_audit_pack(
            assurance_id=assurance_id,
            attestation_path=attestation_path,
            snapshot=refreshed,
        )
        attestation_ok, attestation_detail = self.verify_attestation(attestation_path)
        pack_ok, pack_detail = self.verify_audit_pack(pack_path, receipt_path)
        if not attestation_ok or not pack_ok:
            attestation_path.unlink(missing_ok=True)
            pack_path.unlink(missing_ok=True)
            receipt_path.unlink(missing_ok=True)
            return {
                "status": "blocked",
                "detail": attestation_detail if not attestation_ok else pack_detail,
                "path": "",
            }

        self._write_json(self.root / "latest-reliability-assurance.json", attestation_payload)
        receipt = self._read_json(receipt_path) or {}
        self._write_json(self.root / "latest-reliability-assurance-receipt.json", receipt)
        return ReliabilityAssuranceRecord(
            assurance_id=assurance_id,
            created_at=created_at,
            decision=normalized_decision,
            attestation_path=attestation_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
            source_count=refreshed.verified_pair_count,
            exception_count=refreshed.open_exception_count,
        )

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Reliability assurance attestation is unreadable."
        return self._verify_attestation_payload(payload)

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Reliability assurance receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned_receipt = dict(receipt)
        unsigned_receipt.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned_receipt):
            return False, "Reliability assurance receipt SHA-256 does not match."
        if not pack_path.is_file():
            return False, "Reliability assurance audit pack is missing."
        if str(receipt.get("pack_filename") or "") != pack_path.name:
            return False, "Reliability assurance audit pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "Reliability assurance audit pack size changed."
        if str(receipt.get("pack_sha256") or "") != self._sha256(pack_path):
            return False, "Reliability assurance audit pack SHA-256 changed."

        try:
            with zipfile.ZipFile(pack_path, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Reliability assurance audit pack contains an unsafe path."
                if "manifest.json" not in names or "assurance/attestation.json" not in names:
                    return False, "Reliability assurance audit pack is incomplete."
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                attestation = json.loads(
                    archive.read("assurance/attestation.json").decode("utf-8")
                )
                if not isinstance(manifest, dict) or not isinstance(attestation, dict):
                    return False, "Reliability assurance audit pack JSON is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "Reliability assurance manifest SHA-256 does not match."
                entries = manifest.get("entries")
                if not isinstance(entries, list):
                    return False, "Reliability assurance manifest entries are invalid."
                for record in entries:
                    if not isinstance(record, Mapping):
                        return False, "Reliability assurance manifest entry is invalid."
                    name = str(record.get("path") or "")
                    if name == "manifest.json" or name not in names:
                        return False, "Reliability assurance manifest references an invalid entry."
                    data = archive.read(name)
                    if self._safe_int(record.get("size_bytes"), -1) != len(data):
                        return False, f"Reliability assurance entry size changed: {name}"
                    if str(record.get("sha256") or "") != hashlib.sha256(data).hexdigest():
                        return False, f"Reliability assurance entry SHA-256 changed: {name}"
        except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, KeyError):
            return False, "Reliability assurance audit pack is unreadable."

        ok, detail = self._verify_attestation_payload(attestation)
        if not ok:
            return False, detail
        if str(receipt.get("assurance_id") or "") != str(attestation.get("assurance_id") or ""):
            return False, "Reliability assurance receipt identity does not match."
        return True, "Reliability assurance audit pack is intact and source verified."

    def export_snapshot(self, snapshot: ReliabilityAssuranceSnapshot) -> Path:
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        payload = snapshot.to_dict()
        payload.update(self._safety_contract())
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["snapshot_sha256"] = self._payload_digest(payload)
        self._write_json(path, payload)
        return path

    def _create_audit_pack(
        self,
        *,
        assurance_id: str,
        attestation_path: Path,
        snapshot: ReliabilityAssuranceSnapshot,
    ) -> tuple[Path, Path]:
        pack_path = self.audit_packs_dir / f"{assurance_id}-audit-pack.zip"
        receipt_path = self.receipts_dir / f"{assurance_id}-receipt.json"
        entries: dict[str, bytes] = {
            "assurance/attestation.json": attestation_path.read_bytes(),
            "assurance/snapshot.json": self._json_bytes(snapshot.to_dict()),
        }
        for index, source in enumerate(snapshot.sources, start=1):
            prefix = f"sources/{index:03d}-{source.review_id}"
            entries[f"{prefix}/review.json"] = source.review_path.read_bytes()
            entries[f"{prefix}/decision.json"] = source.decision_path.read_bytes()
        manifest_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "assurance_id": assurance_id,
            "created_at": self._now_iso(),
            "entries": [
                {
                    "path": name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for name, data in sorted(entries.items())
            ],
            "private_data_included": False,
            "automatic_upload": False,
            "automatic_publish": False,
        }
        manifest_payload["manifest_sha256"] = self._payload_digest(manifest_payload)
        entries["manifest.json"] = self._json_bytes(manifest_payload)

        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)

        receipt_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "assurance_id": assurance_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
            "entry_count": len(entries),
            "automatic_upload": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        receipt_payload["receipt_sha256"] = self._payload_digest(receipt_payload)
        self._write_json(receipt_path, receipt_payload)
        return pack_path, receipt_path

    def _verify_attestation_payload(self, payload: Mapping[str, Any]) -> tuple[bool, str]:
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Reliability assurance attestation SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get("human_assurance_completed") is not True:
            return False, "Reliability assurance attestation lacks human assurance."
        if str(payload.get("decision") or "") not in self.ASSURANCE_DECISIONS:
            return False, "Reliability assurance decision is invalid."
        for field in ("owner", "statement", "exception_owner"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "Reliability assurance attestation contains private material."
        sources = payload.get("sources")
        if not isinstance(sources, list) or not sources:
            return False, "Reliability assurance attestation has no source custody."
        for record in sources:
            if not isinstance(record, Mapping):
                return False, "Reliability assurance source record is invalid."
            review_record = record.get("review")
            decision_record = record.get("decision_record")
            ok, detail = self._verify_artifact_record(
                review_record, self.prevention_effectiveness_service.reviews_dir
            )
            if not ok:
                return False, detail
            ok, detail = self._verify_artifact_record(
                decision_record, self.prevention_effectiveness_service.decisions_dir
            )
            if not ok:
                return False, detail
            review_path = self.prevention_effectiveness_service.reviews_dir / str(
                review_record.get("filename") or ""
            )
            decision_path = self.prevention_effectiveness_service.decisions_dir / str(
                decision_record.get("filename") or ""
            )
            ok, detail = self.prevention_effectiveness_service.verify_review(review_path)
            if not ok:
                return False, detail
            ok, detail = self.prevention_effectiveness_service.verify_decision(decision_path)
            if not ok:
                return False, detail
        return True, "Reliability assurance attestation is intact and source verified."

    def _exceptions(
        self, sources: Iterable[ReliabilityAssuranceSource]
    ) -> list[ReliabilityAssuranceException]:
        results: list[ReliabilityAssuranceException] = []
        for source in sources:
            if source.decision == "escalate_prevention":
                results.append(
                    self._exception(
                        source,
                        "prevention_escalation",
                        "critical",
                        "Prevention was escalated and requires governed follow-through.",
                    )
                )
            elif source.decision == "accept_residual_risk":
                results.append(
                    self._exception(
                        source,
                        "accepted_residual_risk",
                        "high",
                        "Residual risk was accepted and requires periodic human review.",
                    )
                )
            elif source.decision == "continue_monitoring":
                severity = "high" if source.age_days > self.MONITORING_REVIEW_DAYS else "medium"
                summary = (
                    "Monitoring decision exceeded the 30-day governance interval."
                    if source.age_days > self.MONITORING_REVIEW_DAYS
                    else "Monitoring remains open until a later effectiveness decision."
                )
                results.append(
                    self._exception(source, "continued_monitoring", severity, summary)
                )
            if source.overdue_action_count:
                results.append(
                    self._exception(
                        source,
                        "overdue_preventive_action",
                        "high",
                        f"Review records {source.overdue_action_count} overdue preventive action(s).",
                    )
                )
            if source.ineffective_pattern_count or source.recurrent_pattern_count:
                results.append(
                    self._exception(
                        source,
                        "recurrence_or_ineffectiveness",
                        "critical",
                        "Verified recurrence or ineffective prevention remains in the source review.",
                    )
                )
        unique: dict[tuple[str, str], ReliabilityAssuranceException] = {}
        for item in results:
            unique[(item.review_id, item.category)] = item
        return sorted(
            unique.values(),
            key=lambda item: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item.severity, 4),
                item.review_id,
                item.category,
            ),
        )

    @staticmethod
    def _exception(
        source: ReliabilityAssuranceSource,
        category: str,
        severity: str,
        summary: str,
    ) -> ReliabilityAssuranceException:
        return ReliabilityAssuranceException(
            code=f"{category}-{source.review_id}",
            review_id=source.review_id,
            baseline_id=source.baseline_id,
            category=category,
            severity=severity,
            summary=summary,
            source_decision=source.decision,
            age_days=source.age_days,
        )

    def _decision_gate(
        self,
        snapshot: ReliabilityAssuranceSnapshot,
        decision: str,
        exception_owner: str,
        next_review_date: str,
    ) -> str:
        if decision == "assure" and snapshot.open_exception_count:
            return "Unqualified assurance is blocked while reliability exceptions remain open."
        if decision == "assure_with_exceptions":
            if not snapshot.open_exception_count:
                return "Use unqualified assurance when no exception remains open."
            if not exception_owner:
                return "Assurance with exceptions requires a privacy-safe human exception owner."
            parsed = self._parse_date(next_review_date)
            if parsed is None:
                return "Assurance with exceptions requires a valid next review date."
            delta = (parsed - self._now().date()).days
            if delta < 1 or delta > 365:
                return "Next exception review must be between 1 and 365 days in the future."
        if decision == "withhold_assurance" and not snapshot.open_exception_count:
            return "Withholding assurance requires at least one open reliability exception."
        return ""

    def _source_record(self, source: ReliabilityAssuranceSource) -> dict[str, object]:
        return {
            "review_id": source.review_id,
            "decision_id": source.decision_id,
            "baseline_id": source.baseline_id,
            "source_decision": source.decision,
            "review": self._path_record(source.review_path),
            "decision_record": self._path_record(source.decision_path),
        }

    def _verify_common_contract(self, payload: Mapping[str, object]) -> tuple[bool, str]:
        if str(payload.get("version") or "") != self.version:
            return False, "Reliability assurance identity does not match the application."
        if str(payload.get("channel") or "") != "stable":
            return False, "Reliability assurance channel is not stable."
        if payload.get("private_data_included") is not False:
            return False, "Reliability assurance record includes private data."
        automatic_flags = (
            "automatic_risk_acceptance",
            "automatic_ticket_creation",
            "automatic_scheduling",
            "automatic_upload",
            "automatic_publish",
            "automatic_patch",
            "automatic_deploy",
            "automatic_rollback",
            "automatic_restart",
        )
        if any(payload.get(flag) is not False for flag in automatic_flags):
            return False, "Reliability assurance record enables an automatic operation."
        return True, "Reliability assurance safety contract is valid."

    @staticmethod
    def _safety_contract() -> dict[str, object]:
        return {
            "automatic_risk_acceptance": False,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_upload": False,
            "automatic_publish": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
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
    ) -> ReliabilityAssuranceGate:
        return ReliabilityAssuranceGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        path = PurePosixPath(str(name))
        return bool(name) and not path.is_absolute() and ".." not in path.parts

    @staticmethod
    def _path_record(path: Path) -> dict[str, object]:
        return {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": ReliabilityAssuranceService._sha256(path),
        }

    def _verify_artifact_record(
        self, record: object, root: Path
    ) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Reliability assurance artifact record is invalid."
        filename = str(record.get("filename") or "")
        if not filename or Path(filename).name != filename:
            return False, "Reliability assurance artifact filename is unsafe."
        path = root / filename
        if not path.is_file():
            return False, f"Reliability assurance artifact is missing: {filename}"
        if self._safe_int(record.get("size_bytes"), -1) != path.stat().st_size:
            return False, f"Reliability assurance artifact size changed: {filename}"
        if str(record.get("sha256") or "") != self._sha256(path):
            return False, f"Reliability assurance artifact SHA-256 changed: {filename}"
        return True, f"Reliability assurance artifact is intact: {filename}"

    def _clean_text(
        self,
        value: str,
        *,
        minimum: int,
        maximum: int,
        allow_empty: bool = False,
    ) -> str | None:
        normalized = " ".join(str(value or "").split())
        if allow_empty and not normalized:
            return ""
        if not minimum <= len(normalized) <= maximum:
            return None
        if self._contains_private_material(normalized):
            return None
        return normalized

    def _contains_private_material(self, value: str) -> bool:
        return bool(self._SECRET_RE.search(value) or self._WINDOWS_PATH_RE.search(value))

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _json_bytes(payload: Mapping[str, object]) -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
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
    def _parse_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _parse_date(value: str) -> date | None:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def _now(self) -> datetime:
        current = self._now_provider()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
