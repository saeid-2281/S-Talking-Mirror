from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.reliability_assurance_renewal import (
    ReliabilityAssuranceRenewalException,
    ReliabilityAssuranceRenewalGate,
    ReliabilityAssuranceRenewalRecord,
    ReliabilityAssuranceRenewalSnapshot,
    ReliabilityAssuranceRenewalSource,
)
from app.services.reliability_assurance_service import ReliabilityAssuranceService


class ReliabilityAssuranceRenewalService:
    """Renew verified reliability assurance without mutating predecessor evidence.

    Phase 69 consumes intact Phase 68 attestation/audit-pack/receipt triplets,
    evaluates lifecycle age and exception follow-up, then creates local immutable
    renewal evidence only after explicit human acknowledgement. It never uploads,
    publishes, schedules, creates tickets, accepts risk, patches, deploys, rolls
    back, restarts or changes any Phase 68 record automatically.
    """

    SCHEMA_VERSION = 1
    DEFAULT_VALIDITY_DAYS = 90
    MIN_VALIDITY_DAYS = 7
    MAX_VALIDITY_DAYS = 3650
    DEFAULT_DUE_SOON_DAYS = 14
    MIN_DUE_SOON_DAYS = 1
    MAX_DUE_SOON_DAYS = 365
    RENEWAL_DECISIONS = (
        "renew",
        "renew_with_follow_up",
        "withhold_renewal",
    )
    SOURCE_DECISIONS = (
        "assure",
        "assure_with_exceptions",
        "withhold_assurance",
    )
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )
    _ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,127}$")

    def __init__(
        self,
        runtime: RuntimeConfig,
        reliability_assurance_service: ReliabilityAssuranceService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.reliability_assurance_service = (
            reliability_assurance_service or ReliabilityAssuranceService(runtime)
        )
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "reliability-assurance-renewal"
        self.snapshots_dir = self.root / "snapshots"
        self.renewals_dir = self.root / "renewals"
        self.follow_up_dir = self.root / "follow-up"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.renewals_dir,
            self.follow_up_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_attestation_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_assurance_service.attestations_dir.glob("assurance-*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_audit_pack_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_assurance_service.audit_packs_dir.glob(
                    "assurance-*-audit-pack.zip"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_receipt_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.reliability_assurance_service.receipts_dir.glob(
                    "assurance-*-receipt.json"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def snapshot(
        self,
        *,
        attestation_paths: Iterable[Path] = (),
        audit_pack_paths: Iterable[Path] = (),
        receipt_paths: Iterable[Path] = (),
        validity_days: int = DEFAULT_VALIDITY_DAYS,
        due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
    ) -> ReliabilityAssuranceRenewalSnapshot:
        attestations = tuple(dict.fromkeys(Path(path) for path in attestation_paths))
        packs = tuple(dict.fromkeys(Path(path) for path in audit_pack_paths))
        receipts = tuple(dict.fromkeys(Path(path) for path in receipt_paths))
        if not attestations:
            attestations = self.default_attestation_paths()
        if not packs:
            packs = self.default_audit_pack_paths()
        if not receipts:
            receipts = self.default_receipt_paths()

        generated_at = self._now_iso()
        snapshot_id = (
            f"renewal-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        gates: list[ReliabilityAssuranceRenewalGate] = []

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
                    else "Assurance renewal requires the verified stable identity."
                ),
                "Run this workflow from the verified stable build.",
            )
        )

        validity_ok = self.MIN_VALIDITY_DAYS <= int(validity_days) <= self.MAX_VALIDITY_DAYS
        due_soon_ok = (
            self.MIN_DUE_SOON_DAYS
            <= int(due_soon_days)
            <= min(self.MAX_DUE_SOON_DAYS, int(validity_days))
        )
        gates.append(
            self._gate(
                "renewal_policy",
                "Renewal validity policy",
                "pass" if validity_ok and due_soon_ok else "block",
                "blocker",
                (
                    f"Validity is {validity_days} day(s); due-soon window is {due_soon_days} day(s)."
                    if validity_ok and due_soon_ok
                    else "Renewal validity or due-soon policy is outside the supported range."
                ),
                "Choose validity 7-3650 days and a due-soon window within validity.",
            )
        )

        attestation_records: dict[str, tuple[Path, dict[str, Any]]] = {}
        pack_records: dict[str, Path] = {}
        receipt_records: dict[str, tuple[Path, dict[str, Any]]] = {}
        rejected = 0

        for path in attestations:
            ok, _detail = self.reliability_assurance_service.verify_attestation(path)
            payload = self._read_json(path)
            assurance_id = str((payload or {}).get("assurance_id") or "")
            if not ok or not payload or not self._ID_RE.fullmatch(assurance_id):
                rejected += 1
                continue
            if assurance_id in attestation_records:
                rejected += 1
                continue
            attestation_records[assurance_id] = (path, payload)

        for path in receipts:
            payload = self._read_json(path)
            assurance_id = str((payload or {}).get("assurance_id") or "")
            if not payload or not self._ID_RE.fullmatch(assurance_id):
                rejected += 1
                continue
            if assurance_id in receipt_records:
                rejected += 1
                continue
            receipt_records[assurance_id] = (path, payload)

        for path in packs:
            assurance_id = self._pack_assurance_id(path)
            if not assurance_id or not self._ID_RE.fullmatch(assurance_id):
                rejected += 1
                continue
            if assurance_id in pack_records:
                rejected += 1
                continue
            pack_records[assurance_id] = path

        all_ids = set(attestation_records) | set(pack_records) | set(receipt_records)
        paired_ids = sorted(
            set(attestation_records) & set(pack_records) & set(receipt_records)
        )
        rejected += len(all_ids - set(paired_ids))

        sources: list[ReliabilityAssuranceRenewalSource] = []
        if validity_ok and due_soon_ok:
            for assurance_id in paired_ids:
                attestation_path, attestation = attestation_records[assurance_id]
                pack_path = pack_records[assurance_id]
                receipt_path, receipt = receipt_records[assurance_id]
                pack_ok, _detail = self.reliability_assurance_service.verify_audit_pack(
                    pack_path, receipt_path
                )
                if not pack_ok:
                    rejected += 1
                    continue
                if str(receipt.get("assurance_id") or "") != assurance_id:
                    rejected += 1
                    continue
                created_at = self._parse_datetime(str(attestation.get("created_at") or ""))
                source_decision = str(attestation.get("decision") or "")
                if created_at is None or source_decision not in self.SOURCE_DECISIONS:
                    rejected += 1
                    continue
                metrics = attestation.get("metrics")
                if not isinstance(metrics, Mapping):
                    rejected += 1
                    continue

                policy_due = created_at.date() + timedelta(days=int(validity_days))
                explicit_due = self._parse_date(str(attestation.get("next_review_date") or ""))
                review_due = min(policy_due, explicit_due) if explicit_due else policy_due
                days_until_review = (review_due - self._now().date()).days
                age_days = max(0, int((self._now() - created_at).total_seconds() // 86400))
                if source_decision == "withhold_assurance":
                    lifecycle_status = "withheld"
                elif days_until_review < 0:
                    lifecycle_status = "overdue"
                elif days_until_review <= int(due_soon_days):
                    lifecycle_status = "due_soon"
                else:
                    lifecycle_status = "current"

                sources.append(
                    ReliabilityAssuranceRenewalSource(
                        assurance_id=assurance_id,
                        assurance_decision=source_decision,
                        created_at=created_at.isoformat(),
                        age_days=age_days,
                        review_due_date=review_due.isoformat(),
                        days_until_review=days_until_review,
                        lifecycle_status=lifecycle_status,
                        attestation_path=attestation_path,
                        audit_pack_path=pack_path,
                        receipt_path=receipt_path,
                        attestation_sha256=self._sha256(attestation_path),
                        audit_pack_sha256=self._sha256(pack_path),
                        receipt_sha256=self._sha256(receipt_path),
                        source_exception_count=self._safe_int(
                            metrics.get("open_exception_count")
                        ),
                    )
                )

        gates.append(
            self._gate(
                "phase68_custody",
                "Phase 68 assurance custody",
                "block" if rejected else "pass",
                "blocker",
                (
                    f"Verified {len(sources)} attestation/audit-pack/receipt triplet(s)."
                    if not rejected
                    else f"Rejected {rejected} invalid, duplicate, unpaired or tampered source item(s)."
                ),
                "Select intact one-to-one Phase 68 assurance triplets.",
            )
        )
        gates.append(
            self._gate(
                "renewal_coverage",
                "Assurance renewal coverage",
                "pass" if sources else "block",
                "blocker",
                (
                    f"Renewal covers {len(sources)} verified assurance record(s)."
                    if sources
                    else "No verified Phase 68 assurance source is available."
                ),
                "Create or select a verified Phase 68 assurance audit pack.",
            )
        )

        exceptions = self._exceptions(sources)
        high_exceptions = sum(item.severity in {"high", "critical"} for item in exceptions)
        if exceptions:
            gates.append(
                self._gate(
                    "follow_up_governance",
                    "Renewal exception follow-up",
                    "warn",
                    "warning",
                    f"{len(exceptions)} lifecycle or source exception(s) require human follow-up.",
                    "Assign a follow-up owner and future review date or withhold renewal.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "follow_up_governance",
                    "Renewal exception follow-up",
                    "pass",
                    "warning",
                    "No lifecycle or source exception requires follow-up.",
                )
            )

        blocker_count = sum(gate.status == "block" for gate in gates)
        if blocker_count:
            status = "blocked"
            summary = f"Assurance renewal is blocked by {blocker_count} gate(s)."
        elif exceptions:
            status = "ready_with_follow_up"
            summary = f"Assurance renewal is ready with {len(exceptions)} follow-up item(s)."
        else:
            status = "ready"
            summary = "Assurance renewal is ready without follow-up exceptions."

        return ReliabilityAssuranceRenewalSnapshot(
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            validity_days=int(validity_days),
            due_soon_days=int(due_soon_days),
            status=status,
            status_summary=summary,
            renewal_allowed=blocker_count == 0,
            selected_attestation_count=len(attestations),
            selected_pack_count=len(packs),
            selected_receipt_count=len(receipts),
            verified_triplet_count=len(sources),
            rejected_source_count=rejected,
            current_count=sum(source.lifecycle_status == "current" for source in sources),
            due_soon_count=sum(source.lifecycle_status == "due_soon" for source in sources),
            overdue_count=sum(source.lifecycle_status == "overdue" for source in sources),
            withheld_count=sum(source.lifecycle_status == "withheld" for source in sources),
            open_exception_count=len(exceptions),
            high_exception_count=high_exceptions,
            sources=tuple(sources),
            exceptions=tuple(exceptions),
            gates=tuple(gates),
        )

    def create_renewal(
        self,
        snapshot: ReliabilityAssuranceRenewalSnapshot,
        *,
        decision: str,
        owner: str,
        statement: str,
        follow_up_owner: str = "",
        next_review_date: str = "",
        acknowledge: bool = False,
    ) -> ReliabilityAssuranceRenewalRecord | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review source custody, lifecycle status and every follow-up item before renewal.",
                "path": "",
            }

        normalized_decision = str(decision or "").strip().lower()
        normalized_owner = self._clean_text(owner, minimum=3, maximum=120)
        normalized_statement = self._clean_text(statement, minimum=24, maximum=1200)
        normalized_follow_up_owner = self._clean_text(
            follow_up_owner, minimum=0, maximum=120, allow_empty=True
        )
        normalized_next_review = str(next_review_date or "").strip()
        if normalized_decision not in self.RENEWAL_DECISIONS:
            return {"status": "blocked", "detail": "Renewal decision is unsupported.", "path": ""}
        if normalized_owner is None or normalized_statement is None:
            return {
                "status": "blocked",
                "detail": "A privacy-safe human owner and renewal statement are required.",
                "path": "",
            }
        if normalized_follow_up_owner is None:
            return {
                "status": "blocked",
                "detail": "Follow-up owner contains a secret or local absolute path.",
                "path": "",
            }

        gate_detail = self._decision_gate(
            snapshot,
            normalized_decision,
            normalized_follow_up_owner,
            normalized_next_review,
        )
        if gate_detail:
            return {"status": "blocked", "detail": gate_detail, "path": ""}

        refreshed = self.snapshot(
            attestation_paths=(source.attestation_path for source in snapshot.sources),
            audit_pack_paths=(source.audit_pack_path for source in snapshot.sources),
            receipt_paths=(source.receipt_path for source in snapshot.sources),
            validity_days=snapshot.validity_days,
            due_soon_days=snapshot.due_soon_days,
        )
        if refreshed.blocker_count:
            return {"status": "blocked", "detail": refreshed.status_summary, "path": ""}
        if {source.assurance_id for source in refreshed.sources} != {
            source.assurance_id for source in snapshot.sources
        }:
            return {
                "status": "blocked",
                "detail": "Phase 68 source identity changed after the renewal snapshot.",
                "path": "",
            }

        renewal_id = f"renewal-{uuid.uuid4().hex[:12]}"
        created_at = self._now_iso()
        renewal_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "renewal_id": renewal_id,
            "snapshot_id": refreshed.snapshot_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "decision": normalized_decision,
            "owner": normalized_owner,
            "statement": normalized_statement,
            "follow_up_owner": normalized_follow_up_owner,
            "next_review_date": normalized_next_review,
            "validity_days": refreshed.validity_days,
            "due_soon_days": refreshed.due_soon_days,
            "metrics": {
                "verified_triplet_count": refreshed.verified_triplet_count,
                "current_count": refreshed.current_count,
                "due_soon_count": refreshed.due_soon_count,
                "overdue_count": refreshed.overdue_count,
                "withheld_count": refreshed.withheld_count,
                "open_exception_count": refreshed.open_exception_count,
                "high_exception_count": refreshed.high_exception_count,
            },
            "sources": [self._source_record(source) for source in refreshed.sources],
            "human_renewal_completed": True,
            "human_follow_up_ownership": bool(normalized_follow_up_owner),
            "external_ticket_updated": False,
            "schedule_updated": False,
            **self._safety_contract(),
        }
        renewal_payload["renewal_sha256"] = self._payload_digest(renewal_payload)
        renewal_path = self.renewals_dir / f"{renewal_id}.json"
        self._write_json(renewal_path, renewal_payload)

        follow_up_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "follow_up_id": f"follow-up-{uuid.uuid4().hex[:12]}",
            "renewal_id": renewal_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "open" if refreshed.exceptions else "not_required",
            "owner": normalized_follow_up_owner,
            "next_review_date": normalized_next_review,
            "items": [item.to_dict() for item in refreshed.exceptions],
            "human_follow_up_reviewed": True,
            "external_ticket_updated": False,
            "schedule_updated": False,
            **self._safety_contract(),
        }
        follow_up_payload["follow_up_sha256"] = self._payload_digest(follow_up_payload)
        follow_up_path = self.follow_up_dir / f"{renewal_id}-follow-up.json"
        self._write_json(follow_up_path, follow_up_payload)

        pack_path, receipt_path = self._create_audit_pack(
            renewal_id=renewal_id,
            renewal_path=renewal_path,
            follow_up_path=follow_up_path,
            snapshot=refreshed,
        )
        renewal_ok, renewal_detail = self.verify_renewal(renewal_path)
        follow_up_ok, follow_up_detail = self.verify_follow_up(follow_up_path)
        pack_ok, pack_detail = self.verify_audit_pack(pack_path, receipt_path)
        if not renewal_ok or not follow_up_ok or not pack_ok:
            for path in (renewal_path, follow_up_path, pack_path, receipt_path):
                path.unlink(missing_ok=True)
            detail = renewal_detail if not renewal_ok else follow_up_detail if not follow_up_ok else pack_detail
            return {"status": "blocked", "detail": detail, "path": ""}

        self._write_json(self.root / "latest-reliability-renewal.json", renewal_payload)
        receipt = self._read_json(receipt_path) or {}
        self._write_json(self.root / "latest-reliability-renewal-receipt.json", receipt)
        return ReliabilityAssuranceRenewalRecord(
            renewal_id=renewal_id,
            created_at=created_at,
            decision=normalized_decision,
            renewal_path=renewal_path,
            follow_up_path=follow_up_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
            source_count=refreshed.verified_triplet_count,
            exception_count=refreshed.open_exception_count,
        )

    def verify_renewal(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Reliability assurance renewal is unreadable."
        expected = str(payload.get("renewal_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("renewal_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Reliability assurance renewal SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get("human_renewal_completed") is not True:
            return False, "Reliability assurance renewal lacks human acknowledgement."
        if str(payload.get("decision") or "") not in self.RENEWAL_DECISIONS:
            return False, "Reliability assurance renewal decision is invalid."
        for field in ("owner", "statement", "follow_up_owner"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "Reliability assurance renewal contains private material."
        sources = payload.get("sources")
        if not isinstance(sources, list) or not sources:
            return False, "Reliability assurance renewal has no source custody."
        for record in sources:
            if not isinstance(record, Mapping):
                return False, "Reliability assurance renewal source record is invalid."
            assurance_id = str(record.get("assurance_id") or "")
            if not self._ID_RE.fullmatch(assurance_id):
                return False, "Reliability assurance renewal source identity is invalid."
            attestation_record = record.get("attestation")
            pack_record = record.get("audit_pack")
            receipt_record = record.get("receipt")
            ok, detail = self._verify_artifact_record(
                attestation_record, self.reliability_assurance_service.attestations_dir
            )
            if not ok:
                return False, detail
            ok, detail = self._verify_artifact_record(
                pack_record, self.reliability_assurance_service.audit_packs_dir
            )
            if not ok:
                return False, detail
            ok, detail = self._verify_artifact_record(
                receipt_record, self.reliability_assurance_service.receipts_dir
            )
            if not ok:
                return False, detail
            attestation_path = self.reliability_assurance_service.attestations_dir / str(
                attestation_record.get("filename") or ""
            )
            pack_path = self.reliability_assurance_service.audit_packs_dir / str(
                pack_record.get("filename") or ""
            )
            receipt_path = self.reliability_assurance_service.receipts_dir / str(
                receipt_record.get("filename") or ""
            )
            ok, detail = self.reliability_assurance_service.verify_attestation(attestation_path)
            if not ok:
                return False, detail
            ok, detail = self.reliability_assurance_service.verify_audit_pack(
                pack_path, receipt_path
            )
            if not ok:
                return False, detail
        return True, "Reliability assurance renewal is intact and source verified."

    def verify_follow_up(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Reliability assurance follow-up register is unreadable."
        expected = str(payload.get("follow_up_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("follow_up_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Reliability assurance follow-up SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("human_follow_up_reviewed") is not True:
            return False, "Reliability assurance follow-up lacks human review."
        if str(payload.get("status") or "") not in {"open", "not_required"}:
            return False, "Reliability assurance follow-up status is invalid."
        if self._contains_private_material(str(payload.get("owner") or "")):
            return False, "Reliability assurance follow-up contains private material."
        items = payload.get("items")
        if not isinstance(items, list):
            return False, "Reliability assurance follow-up items are invalid."
        if payload.get("status") == "open":
            if not items:
                return False, "Open reliability assurance follow-up has no items."
            owner = str(payload.get("owner") or "")
            next_review = self._parse_date(str(payload.get("next_review_date") or ""))
            if not owner or next_review is None:
                return False, "Open reliability assurance follow-up lacks owner or review date."
        return True, "Reliability assurance follow-up register is intact."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Reliability assurance renewal receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned_receipt = dict(receipt)
        unsigned_receipt.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned_receipt):
            return False, "Reliability assurance renewal receipt SHA-256 does not match."
        if not pack_path.is_file():
            return False, "Reliability assurance renewal audit pack is missing."
        if str(receipt.get("pack_filename") or "") != pack_path.name:
            return False, "Reliability assurance renewal audit pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "Reliability assurance renewal audit pack size changed."
        if str(receipt.get("pack_sha256") or "") != self._sha256(pack_path):
            return False, "Reliability assurance renewal audit pack SHA-256 changed."

        try:
            with zipfile.ZipFile(pack_path, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Reliability assurance renewal audit pack contains an unsafe path."
                required = {
                    "manifest.json",
                    "renewal/record.json",
                    "renewal/follow-up.json",
                }
                if not required.issubset(names):
                    return False, "Reliability assurance renewal audit pack is incomplete."
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                renewal = json.loads(archive.read("renewal/record.json").decode("utf-8"))
                follow_up = json.loads(archive.read("renewal/follow-up.json").decode("utf-8"))
                if not all(isinstance(item, dict) for item in (manifest, renewal, follow_up)):
                    return False, "Reliability assurance renewal audit pack JSON is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "Reliability assurance renewal manifest SHA-256 does not match."
                entries = manifest.get("entries")
                if not isinstance(entries, list):
                    return False, "Reliability assurance renewal manifest entries are invalid."
                for record in entries:
                    if not isinstance(record, Mapping):
                        return False, "Reliability assurance renewal manifest entry is invalid."
                    name = str(record.get("path") or "")
                    if name == "manifest.json" or name not in names:
                        return False, "Reliability assurance renewal manifest references an invalid entry."
                    data = archive.read(name)
                    if self._safe_int(record.get("size_bytes"), -1) != len(data):
                        return False, f"Reliability assurance renewal entry size changed: {name}"
                    if str(record.get("sha256") or "") != hashlib.sha256(data).hexdigest():
                        return False, f"Reliability assurance renewal entry SHA-256 changed: {name}"
        except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, KeyError):
            return False, "Reliability assurance renewal audit pack is unreadable."

        renewal_ok, renewal_detail = self._verify_renewal_payload(renewal)
        if not renewal_ok:
            return False, renewal_detail
        follow_up_ok, follow_up_detail = self._verify_follow_up_payload(follow_up)
        if not follow_up_ok:
            return False, follow_up_detail
        if str(receipt.get("renewal_id") or "") != str(renewal.get("renewal_id") or ""):
            return False, "Reliability assurance renewal receipt identity does not match."
        if str(follow_up.get("renewal_id") or "") != str(renewal.get("renewal_id") or ""):
            return False, "Reliability assurance follow-up identity does not match."
        return True, "Reliability assurance renewal audit pack is intact and source verified."

    def export_snapshot(self, snapshot: ReliabilityAssuranceRenewalSnapshot) -> Path:
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
        renewal_id: str,
        renewal_path: Path,
        follow_up_path: Path,
        snapshot: ReliabilityAssuranceRenewalSnapshot,
    ) -> tuple[Path, Path]:
        pack_path = self.audit_packs_dir / f"{renewal_id}-audit-pack.zip"
        receipt_path = self.receipts_dir / f"{renewal_id}-receipt.json"
        entries: dict[str, bytes] = {
            "renewal/record.json": renewal_path.read_bytes(),
            "renewal/follow-up.json": follow_up_path.read_bytes(),
            "renewal/snapshot.json": self._json_bytes(snapshot.to_dict()),
        }
        for index, source in enumerate(snapshot.sources, start=1):
            prefix = f"sources/{index:03d}-{source.assurance_id}"
            entries[f"{prefix}/attestation.json"] = source.attestation_path.read_bytes()
            entries[f"{prefix}/audit-pack.zip"] = source.audit_pack_path.read_bytes()
            entries[f"{prefix}/receipt.json"] = source.receipt_path.read_bytes()
        manifest_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "renewal_id": renewal_id,
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
            "renewal_id": renewal_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
            "entry_count": len(entries),
            **self._safety_contract(),
        }
        receipt_payload["receipt_sha256"] = self._payload_digest(receipt_payload)
        self._write_json(receipt_path, receipt_payload)
        return pack_path, receipt_path

    def _verify_renewal_payload(self, payload: Mapping[str, Any]) -> tuple[bool, str]:
        expected = str(payload.get("renewal_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("renewal_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Reliability assurance renewal SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("human_renewal_completed") is not True:
            return False, "Reliability assurance renewal lacks human acknowledgement."
        if str(payload.get("decision") or "") not in self.RENEWAL_DECISIONS:
            return False, "Reliability assurance renewal decision is invalid."
        return True, "Reliability assurance renewal payload is intact."

    def _verify_follow_up_payload(self, payload: Mapping[str, Any]) -> tuple[bool, str]:
        expected = str(payload.get("follow_up_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("follow_up_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Reliability assurance follow-up SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("human_follow_up_reviewed") is not True:
            return False, "Reliability assurance follow-up lacks human review."
        return True, "Reliability assurance follow-up payload is intact."

    def _exceptions(
        self, sources: Iterable[ReliabilityAssuranceRenewalSource]
    ) -> list[ReliabilityAssuranceRenewalException]:
        results: list[ReliabilityAssuranceRenewalException] = []
        for source in sources:
            if source.lifecycle_status == "withheld":
                results.append(
                    self._exception(
                        source,
                        "assurance_withheld",
                        "critical",
                        "The source assurance was withheld and cannot be renewed unqualified.",
                    )
                )
            elif source.lifecycle_status == "overdue":
                results.append(
                    self._exception(
                        source,
                        "renewal_overdue",
                        "critical",
                        "The source assurance review date has passed.",
                    )
                )
            elif source.lifecycle_status == "due_soon":
                results.append(
                    self._exception(
                        source,
                        "renewal_due_soon",
                        "medium",
                        "The source assurance is inside the configured renewal window.",
                    )
                )
            if source.assurance_decision == "assure_with_exceptions":
                results.append(
                    self._exception(
                        source,
                        "carried_assurance_exception",
                        "high",
                        "The source assurance contains governed exceptions that require follow-up.",
                    )
                )
            if source.source_exception_count:
                results.append(
                    self._exception(
                        source,
                        "source_exception_backlog",
                        "high",
                        f"The source assurance records {source.source_exception_count} open exception(s).",
                    )
                )
        unique: dict[tuple[str, str], ReliabilityAssuranceRenewalException] = {}
        for item in results:
            unique[(item.assurance_id, item.category)] = item
        return sorted(
            unique.values(),
            key=lambda item: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item.severity, 4),
                item.assurance_id,
                item.category,
            ),
        )

    @staticmethod
    def _exception(
        source: ReliabilityAssuranceRenewalSource,
        category: str,
        severity: str,
        summary: str,
    ) -> ReliabilityAssuranceRenewalException:
        return ReliabilityAssuranceRenewalException(
            code=f"{category}-{source.assurance_id}",
            assurance_id=source.assurance_id,
            category=category,
            severity=severity,
            summary=summary,
            due_date=source.review_due_date,
        )

    def _decision_gate(
        self,
        snapshot: ReliabilityAssuranceRenewalSnapshot,
        decision: str,
        follow_up_owner: str,
        next_review_date: str,
    ) -> str:
        if decision == "renew" and snapshot.open_exception_count:
            return "Unqualified renewal is blocked while assurance follow-up exceptions remain open."
        if decision in {"renew_with_follow_up", "withhold_renewal"}:
            if not snapshot.open_exception_count:
                if decision == "renew_with_follow_up":
                    return "Use unqualified renewal when no follow-up exception remains open."
                return "Withholding renewal requires at least one lifecycle or source exception."
            if not follow_up_owner:
                return "Governed renewal follow-up requires a privacy-safe human owner."
            parsed = self._parse_date(next_review_date)
            if parsed is None:
                return "Governed renewal follow-up requires a valid next review date."
            delta = (parsed - self._now().date()).days
            if delta < 1 or delta > 365:
                return "Next follow-up review must be between 1 and 365 days in the future."
        return ""

    def _source_record(self, source: ReliabilityAssuranceRenewalSource) -> dict[str, object]:
        return {
            "assurance_id": source.assurance_id,
            "assurance_decision": source.assurance_decision,
            "lifecycle_status": source.lifecycle_status,
            "review_due_date": source.review_due_date,
            "attestation": self._path_record(source.attestation_path),
            "audit_pack": self._path_record(source.audit_pack_path),
            "receipt": self._path_record(source.receipt_path),
        }

    def _verify_common_contract(self, payload: Mapping[str, object]) -> tuple[bool, str]:
        if str(payload.get("version") or "") != self.version:
            return False, "Reliability assurance renewal identity does not match the application."
        if str(payload.get("channel") or "") != "stable":
            return False, "Reliability assurance renewal channel is not stable."
        if payload.get("private_data_included") is not False:
            return False, "Reliability assurance renewal includes private data."
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
            return False, "Reliability assurance renewal enables an automatic operation."
        return True, "Reliability assurance renewal safety contract is valid."

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
    ) -> ReliabilityAssuranceRenewalGate:
        return ReliabilityAssuranceRenewalGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _pack_assurance_id(path: Path) -> str:
        suffix = "-audit-pack.zip"
        return path.name[: -len(suffix)] if path.name.endswith(suffix) else ""

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        path = PurePosixPath(str(name))
        return bool(name) and not path.is_absolute() and ".." not in path.parts

    @staticmethod
    def _path_record(path: Path) -> dict[str, object]:
        return {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": ReliabilityAssuranceRenewalService._sha256(path),
        }

    def _verify_artifact_record(self, record: object, root: Path) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Reliability assurance renewal artifact record is invalid."
        filename = str(record.get("filename") or "")
        if not filename or Path(filename).name != filename:
            return False, "Reliability assurance renewal artifact filename is unsafe."
        path = root / filename
        if not path.is_file():
            return False, f"Reliability assurance renewal artifact is missing: {filename}"
        if self._safe_int(record.get("size_bytes"), -1) != path.stat().st_size:
            return False, f"Reliability assurance renewal artifact size changed: {filename}"
        if str(record.get("sha256") or "") != self._sha256(path):
            return False, f"Reliability assurance renewal artifact SHA-256 changed: {filename}"
        return True, f"Reliability assurance renewal artifact is intact: {filename}"

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
