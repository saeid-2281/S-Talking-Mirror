from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.operations_command_center import (
    OperationsCommandSnapshot,
    OperationsDomainStatus,
)


class OperationsCommandCenterService:
    """Read-only operational summary backed by verified production evidence."""

    SCHEMA_VERSION = 1
    DOMAIN_CODES = (
        "health",
        "incidents",
        "slo",
        "capacity",
        "recovery",
        "providers",
        "billing",
        "audit",
    )
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|/home/|/users/)")

    def __init__(
        self,
        runtime: RuntimeConfig,
        post_ga_maintenance_service: Any,
        incident_triage_service: Any,
        incident_resolution_service: Any,
        service_level_objectives_service: Any,
        capacity_readiness_service: Any,
        service_continuity_service: Any,
        provider_governance_service: Any,
        financial_audit_service: Any,
        reliability_assurance_renewal_service: Any,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.post_ga_maintenance_service = post_ga_maintenance_service
        self.incident_triage_service = incident_triage_service
        self.incident_resolution_service = incident_resolution_service
        self.service_level_objectives_service = service_level_objectives_service
        self.capacity_readiness_service = capacity_readiness_service
        self.service_continuity_service = service_continuity_service
        self.provider_governance_service = provider_governance_service
        self.financial_audit_service = financial_audit_service
        self.reliability_assurance_renewal_service = (
            reliability_assurance_renewal_service
        )
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "operations-command-center"
        self.snapshots_dir = self.root / "snapshots"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self, *, project_id: int | None = None) -> OperationsCommandSnapshot:
        domains = (
            self._health_domain(),
            self._incident_domain(),
            self._slo_domain(),
            self._capacity_domain(),
            self._recovery_domain(),
            self._provider_domain(),
            self._billing_domain(),
            self._audit_domain(),
        )
        critical = sum(item.status == "critical" for item in domains)
        warning = sum(item.status == "warning" for item in domains)
        unknown = sum(item.status == "unknown" for item in domains)
        healthy = sum(item.status == "healthy" for item in domains)
        overall = "critical" if critical else "attention" if warning or unknown else "healthy"
        summary = (
            f"{healthy} healthy · {warning} warning · {critical} critical · "
            f"{unknown} unknown"
        )
        recommendations = tuple(
            f"Review {item.label}: {item.headline}"
            for item in domains
            if item.status in {"critical", "warning", "unknown"}
        ) or ("No immediate operational review is required.",)
        return OperationsCommandSnapshot(
            snapshot_id=f"operations-command-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            project_id=project_id,
            overall_status=overall,
            status_summary=summary,
            domains=domains,
            recommendations=recommendations,
        )

    def export_snapshot(self, snapshot: OperationsCommandSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-operations-command-center.json", payload)
        return path

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Operations command-center snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Operations command-center snapshot SHA-256 changed."
        if not self._verify_safety_contract(payload):
            return False, "Operations command-center safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Operations command-center snapshot contains private material."
        if str(payload.get("overall_status") or "") not in {
            "healthy",
            "attention",
            "critical",
        }:
            return False, "Operations command-center overall status is invalid."
        domains = payload.get("domains")
        if not isinstance(domains, list) or len(domains) != len(self.DOMAIN_CODES):
            return False, "Operations command-center domain set is incomplete."
        codes = tuple(str(item.get("code") or "") for item in domains if isinstance(item, Mapping))
        if codes != self.DOMAIN_CODES:
            return False, "Operations command-center domain order changed."
        for item in domains:
            if not isinstance(item, Mapping):
                return False, "Operations command-center domain record is invalid."
            status = str(item.get("status") or "")
            if status not in {"healthy", "warning", "critical", "unknown"}:
                return False, "Operations command-center domain status is invalid."
            filename = str(item.get("evidence_filename") or "")
            digest = str(item.get("evidence_sha256") or "")
            if filename:
                source = self._evidence_path(str(item.get("code") or ""), filename)
                if source is None or not source.is_file():
                    return False, f"Operations evidence is missing: {filename}"
                if digest != self._sha256(source):
                    return False, f"Operations evidence custody changed: {filename}"
        return True, "Operations command-center snapshot and source custody verified."

    def _health_domain(self) -> OperationsDomainStatus:
        path = Path(self.post_ga_maintenance_service.default_baseline_path())
        if not path.is_file():
            return self._unknown(
                "health",
                "Production health",
                "Post-GA baseline has not been recorded.",
                "post-ga-maintenance",
            )
        ok, detail = self.post_ga_maintenance_service.verify_baseline(path)
        if not ok:
            return self._critical(
                "health",
                "Production health",
                "Post-GA baseline failed verification.",
                detail,
                path,
                "post-ga-maintenance",
            )
        payload = self._read_json(path) or {}
        source_status = str(payload.get("status") or "")
        status = {
            "ready": "healthy",
            "ready_with_warnings": "warning",
            "blocked": "critical",
        }.get(source_status, "warning")
        rollout = self._safe_int(payload.get("rollout_percentage"), 0)
        age = self._safe_int(payload.get("evidence_age_days"), -1)
        warnings = self._safe_int(payload.get("warning_count"), 0)
        return self._domain(
            "health",
            "Production health",
            status,
            f"Post-GA maintenance is {source_status or 'verified'}.",
            f"{rollout}% rollout",
            f"Evidence age {age} day(s); {warnings} warning(s).",
            path,
            "post-ga-maintenance",
        )

    def _incident_domain(self) -> OperationsDomainStatus:
        closures: set[str] = set()
        invalid = 0
        latest_evidence: Path | None = None
        for path in self._sorted_files(
            self.incident_resolution_service.closures_dir, "*-closure.json"
        ):
            ok, _detail = self.incident_resolution_service.verify_closure(path)
            if not ok:
                invalid += 1
                latest_evidence = latest_evidence or path
                continue
            payload = self._read_json(path) or {}
            case_id = str(payload.get("case_id") or "")
            if case_id:
                closures.add(case_id)
            latest_evidence = latest_evidence or path

        active: list[dict[str, object]] = []
        for path in self._sorted_files(self.incident_triage_service.cases_dir, "*.json"):
            ok, _detail = self.incident_triage_service.verify_case(path)
            if not ok:
                invalid += 1
                latest_evidence = latest_evidence or path
                continue
            payload = self._read_json(path) or {}
            if str(payload.get("case_id") or "") not in closures:
                payload["_path"] = path
                active.append(payload)
                latest_evidence = latest_evidence or path

        if invalid:
            return self._critical(
                "incidents",
                "Incidents",
                "Incident evidence failed verification.",
                f"{invalid} incident artifact(s) are invalid.",
                latest_evidence,
                "incident-triage",
            )
        if not active:
            return self._domain(
                "incidents",
                "Incidents",
                "healthy",
                "No unresolved local incident cases.",
                "0 active",
                f"{len(closures)} verified closure(s) are recorded.",
                latest_evidence,
                "incident-triage",
            )
        priorities = [str(item.get("priority") or "P3").upper() for item in active]
        critical = any(priority in {"P0", "P1"} for priority in priorities)
        highest = min(priorities, key=lambda value: self._priority_rank(value))
        evidence = active[0].get("_path")
        return self._domain(
            "incidents",
            "Incidents",
            "critical" if critical else "warning",
            f"{len(active)} unresolved incident case(s).",
            f"Highest {highest}",
            "Human triage or closure review is required.",
            evidence if isinstance(evidence, Path) else latest_evidence,
            "incident-triage",
        )

    def _slo_domain(self) -> OperationsDomainStatus:
        path = self._latest(self.service_level_objectives_service.decisions_dir, "*.json")
        if path is None:
            return self._unknown(
                "slo",
                "SLO & error budget",
                "No verified SLO release decision is available.",
                "service-level-objectives",
            )
        ok, detail = self.service_level_objectives_service.verify_decision(path)
        if not ok:
            return self._critical(
                "slo",
                "SLO & error budget",
                "Latest SLO decision failed verification.",
                detail,
                path,
                "service-level-objectives",
            )
        payload = self._read_json(path) or {}
        decision = str(payload.get("decision") or "")
        snapshot_path = self.service_level_objectives_service.snapshots_dir / str(
            payload.get("snapshot_filename") or ""
        )
        snapshot = self._read_json(snapshot_path) or {}
        availability = self._safe_float(snapshot.get("availability_percent"), 0.0)
        remaining = self._safe_float(snapshot.get("error_budget_remaining_minutes"), 0.0)
        status = {"allow": "healthy", "manual_review": "warning", "hold": "critical"}.get(
            decision, "warning"
        )
        return self._domain(
            "slo",
            "SLO & error budget",
            status,
            f"Release-safety decision: {decision or 'unknown'}.",
            f"{availability:.3f}% availability",
            f"Error budget remaining: {remaining:.1f} minute(s).",
            path,
            "service-level-objectives",
        )

    def _capacity_domain(self) -> OperationsDomainStatus:
        path = self._latest(self.capacity_readiness_service.decisions_dir, "*.json")
        if path is None:
            return self._unknown(
                "capacity",
                "Capacity",
                "No verified capacity decision is available.",
                "capacity-readiness",
            )
        ok, detail = self.capacity_readiness_service.verify_decision(path)
        if not ok:
            return self._critical(
                "capacity",
                "Capacity",
                "Latest capacity decision failed verification.",
                detail,
                path,
                "capacity-readiness",
            )
        payload = self._read_json(path) or {}
        decision = str(payload.get("decision") or "")
        snapshot_path = self.capacity_readiness_service.snapshots_dir / str(
            payload.get("snapshot_filename") or ""
        )
        snapshot = self._read_json(snapshot_path) or {}
        headroom = self._safe_float(snapshot.get("projected_headroom_percent"), 0.0)
        days = snapshot.get("days_to_saturation")
        status = {
            "allow_release": "healthy",
            "scale_before_release": "warning",
            "prepare_degraded_mode": "warning",
            "hold_release": "critical",
        }.get(decision, "warning")
        saturation = "not projected" if days is None else f"{self._safe_float(days):.1f} day(s)"
        return self._domain(
            "capacity",
            "Capacity",
            status,
            f"Capacity decision: {decision or 'unknown'}.",
            f"{headroom:.1f}% projected headroom",
            f"Saturation: {saturation}.",
            path,
            "capacity-readiness",
        )

    def _recovery_domain(self) -> OperationsDomainStatus:
        path = self._latest(self.service_continuity_service.attestations_dir, "*.json")
        if path is None:
            return self._unknown(
                "recovery",
                "Recovery",
                "No continuity-drill attestation is available.",
                "service-continuity",
            )
        ok, detail = self.service_continuity_service.verify_attestation(path)
        if not ok:
            return self._critical(
                "recovery",
                "Recovery",
                "Latest recovery attestation failed verification.",
                detail,
                path,
                "service-continuity",
            )
        payload = self._read_json(path) or {}
        source_status = str(payload.get("status") or "")
        result_path = self.service_continuity_service.results_dir / str(
            payload.get("result_filename") or ""
        )
        result = self._read_json(result_path) or {}
        restore = self._safe_int(result.get("actual_restore_minutes"), 0)
        rto = self._safe_int(result.get("rto_target_minutes"), 0)
        outcome = str(result.get("outcome") or "unknown")
        return self._domain(
            "recovery",
            "Recovery",
            "healthy" if source_status == "verified" else "critical",
            f"Continuity attestation: {source_status or 'unknown'}.",
            f"Restore {restore}/{rto} min",
            f"Latest drill outcome: {outcome}.",
            path,
            "service-continuity",
        )

    def _provider_domain(self) -> OperationsDomainStatus:
        path = self._latest(self.provider_governance_service.governance_dir, "*.json")
        if path is None:
            return self._unknown(
                "providers",
                "Providers",
                "No provider governance baseline is available.",
                "provider-governance",
            )
        ok, detail = self.provider_governance_service.verify_governance(path)
        if not ok:
            return self._critical(
                "providers",
                "Providers",
                "Latest provider governance failed verification.",
                detail,
                path,
                "provider-governance",
            )
        payload = self._read_json(path) or {}
        decisions = payload.get("provider_decisions")
        decisions = decisions if isinstance(decisions, list) else []
        values = [str(item.get("decision") or "") for item in decisions if isinstance(item, Mapping)]
        preferred = values.count("preferred")
        approved = values.count("approved")
        watch = values.count("watch")
        restricted = values.count("restricted")
        total = len(values)
        if total and restricted == total:
            status = "critical"
        elif restricted or watch:
            status = "warning"
        elif total:
            status = "healthy"
        else:
            status = "unknown"
        return self._domain(
            "providers",
            "Providers",
            status,
            "Provider governance baseline is verified.",
            f"{preferred} preferred · {approved} approved",
            f"{watch} watch · {restricted} restricted.",
            path,
            "provider-governance",
        )

    def _billing_domain(self) -> OperationsDomainStatus:
        path = self._latest(self.financial_audit_service.audits_dir, "*.json")
        if path is None:
            return self._unknown(
                "billing",
                "Billing",
                "No financial-audit record is available.",
                "financial-audit",
            )
        ok, detail = self.financial_audit_service.verify_audit(path)
        if not ok:
            return self._critical(
                "billing",
                "Billing",
                "Latest financial audit failed verification.",
                detail,
                path,
                "financial-audit",
            )
        payload = self._read_json(path) or {}
        residual = abs(self._safe_float(payload.get("total_residual_variance"), 0.0))
        invoice_count = self._safe_int(payload.get("invoice_count"), 0)
        status = "healthy" if residual <= 0.01 else "critical"
        return self._domain(
            "billing",
            "Billing",
            status,
            "Financial audit evidence is verified.",
            f"{invoice_count} invoice(s)",
            f"Residual variance: {residual:.2f}.",
            path,
            "financial-audit",
        )

    def _audit_domain(self) -> OperationsDomainStatus:
        path = self._latest(
            self.reliability_assurance_renewal_service.renewals_dir, "*.json"
        )
        if path is None:
            return self._unknown(
                "audit",
                "Audit assurance",
                "No reliability-assurance renewal is available.",
                "assurance-renewal",
            )
        ok, detail = self.reliability_assurance_renewal_service.verify_renewal(path)
        if not ok:
            return self._critical(
                "audit",
                "Audit assurance",
                "Latest assurance renewal failed verification.",
                detail,
                path,
                "assurance-renewal",
            )
        payload = self._read_json(path) or {}
        decision = str(payload.get("decision") or "")
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else {}
        exceptions = self._safe_int(metrics.get("open_exception_count"), 0)
        high = self._safe_int(metrics.get("high_exception_count"), 0)
        status = {
            "renew": "healthy",
            "renew_with_follow_up": "warning",
            "withhold_renewal": "critical",
        }.get(decision, "warning")
        return self._domain(
            "audit",
            "Audit assurance",
            status,
            f"Assurance decision: {decision or 'unknown'}.",
            f"{exceptions} open exception(s)",
            f"{high} high-severity exception(s).",
            path,
            "assurance-renewal",
        )

    def _domain(
        self,
        code: str,
        label: str,
        status: str,
        headline: str,
        metric: str,
        detail: str,
        evidence_path: Path | None,
        action_code: str,
    ) -> OperationsDomainStatus:
        evidence = Path(evidence_path) if evidence_path else None
        return OperationsDomainStatus(
            code=code,
            label=label,
            status=status,
            headline=headline,
            metric=metric,
            detail=detail,
            evidence_filename=evidence.name if evidence and evidence.is_file() else "",
            evidence_sha256=self._sha256(evidence) if evidence and evidence.is_file() else "",
            action_code=action_code,
        )

    def _unknown(
        self, code: str, label: str, headline: str, action_code: str
    ) -> OperationsDomainStatus:
        return self._domain(
            code,
            label,
            "unknown",
            headline,
            "No evidence",
            "Create or refresh the corresponding verified operational evidence.",
            None,
            action_code,
        )

    def _critical(
        self,
        code: str,
        label: str,
        headline: str,
        detail: str,
        path: Path | None,
        action_code: str,
    ) -> OperationsDomainStatus:
        return self._domain(
            code,
            label,
            "critical",
            headline,
            "Verification failed",
            detail,
            path,
            action_code,
        )

    def _evidence_path(self, code: str, filename: str) -> Path | None:
        roots: dict[str, tuple[Path, ...]] = {
            "health": (
                Path(self.post_ga_maintenance_service.root),
                Path(self.post_ga_maintenance_service.baseline_root),
            ),
            "incidents": (
                Path(self.incident_triage_service.cases_dir),
                Path(self.incident_resolution_service.closures_dir),
            ),
            "slo": (Path(self.service_level_objectives_service.decisions_dir),),
            "capacity": (Path(self.capacity_readiness_service.decisions_dir),),
            "recovery": (Path(self.service_continuity_service.attestations_dir),),
            "providers": (Path(self.provider_governance_service.governance_dir),),
            "billing": (Path(self.financial_audit_service.audits_dir),),
            "audit": (Path(self.reliability_assurance_renewal_service.renewals_dir),),
        }
        for root in roots.get(code, ()):  # pragma: no branch - fixed domain set
            candidate = root / filename
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _priority_rank(value: str) -> int:
        return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(value, 4)

    @staticmethod
    def _sorted_files(directory: Path, pattern: str) -> tuple[Path, ...]:
        root = Path(directory)
        if not root.is_dir():
            return ()
        return tuple(
            sorted(
                (path for path in root.glob(pattern) if path.is_file()),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
                reverse=True,
            )
        )

    def _latest(self, directory: Path, pattern: str) -> Path | None:
        items = self._sorted_files(directory, pattern)
        return items[0] if items else None

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "read_only": True,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_provider_change": False,
            "automatic_billing_change": False,
            "automatic_ticket_change": False,
            "automatic_publish": False,
            "private_data_included": False,
        }

    @classmethod
    def _verify_safety_contract(cls, payload: Mapping[str, object]) -> bool:
        contract = cls._safety_contract()
        return all(payload.get(key) == value for key, value in contract.items())

    @classmethod
    def _contains_private_payload(cls, payload: object) -> bool:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
        return bool(cls._SECRET_RE.search(text) or cls._ABSOLUTE_PATH_RE.search(text))

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @classmethod
    def _payload_digest(cls, payload: Mapping[str, object]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _now_iso(self) -> str:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
