from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.operations_command_center_service import OperationsCommandCenterService


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


class _Verifier:
    def _verify(self, path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "unreadable"
        return (bool(payload.get("valid", True)), "verified" if payload.get("valid", True) else "tampered")


class _PostGa(_Verifier):
    def __init__(self, root: Path) -> None:
        self.root = root / "post-ga-maintenance"
        self.baseline_root = self.root / "baselines"
        self.root.mkdir(parents=True, exist_ok=True)
        self.baseline_root.mkdir(parents=True, exist_ok=True)

    def default_baseline_path(self) -> Path:
        return self.root / "post-ga-maintenance-baseline.json"

    def verify_baseline(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _IncidentTriage(_Verifier):
    def __init__(self, root: Path) -> None:
        self.cases_dir = root / "incident-triage" / "cases"
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def verify_case(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _IncidentResolution(_Verifier):
    def __init__(self, root: Path) -> None:
        self.closures_dir = root / "incident-resolution" / "closures"
        self.closures_dir.mkdir(parents=True, exist_ok=True)

    def verify_closure(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _Slo(_Verifier):
    def __init__(self, root: Path) -> None:
        self.decisions_dir = root / "service-level-objectives" / "decisions"
        self.snapshots_dir = root / "service-level-objectives" / "snapshots"
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _Capacity(_Verifier):
    def __init__(self, root: Path) -> None:
        self.decisions_dir = root / "capacity-readiness" / "decisions"
        self.snapshots_dir = root / "capacity-readiness" / "snapshots"
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _Continuity(_Verifier):
    def __init__(self, root: Path) -> None:
        self.attestations_dir = root / "service-continuity" / "attestations"
        self.results_dir = root / "service-continuity" / "results"
        self.attestations_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _ProviderGovernance(_Verifier):
    def __init__(self, root: Path) -> None:
        self.governance_dir = root / "provider-governance" / "records"
        self.governance_dir.mkdir(parents=True, exist_ok=True)

    def verify_governance(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _FinancialAudit(_Verifier):
    def __init__(self, root: Path) -> None:
        self.audits_dir = root / "financial-audit" / "audits"
        self.audits_dir.mkdir(parents=True, exist_ok=True)

    def verify_audit(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


class _Renewal(_Verifier):
    def __init__(self, root: Path) -> None:
        self.renewals_dir = root / "reliability-assurance-renewal" / "renewals"
        self.renewals_dir.mkdir(parents=True, exist_ok=True)

    def verify_renewal(self, path: Path) -> tuple[bool, str]:
        return self._verify(path)


def _service(root: Path) -> tuple[OperationsCommandCenterService, dict[str, object]]:
    runtime = RuntimeConfig.from_root(root)
    runtime.ensure_directories()
    services: dict[str, object] = {
        "post_ga": _PostGa(runtime.artifacts_dir),
        "triage": _IncidentTriage(runtime.artifacts_dir),
        "resolution": _IncidentResolution(runtime.artifacts_dir),
        "slo": _Slo(runtime.artifacts_dir),
        "capacity": _Capacity(runtime.artifacts_dir),
        "continuity": _Continuity(runtime.artifacts_dir),
        "provider": _ProviderGovernance(runtime.artifacts_dir),
        "financial": _FinancialAudit(runtime.artifacts_dir),
        "renewal": _Renewal(runtime.artifacts_dir),
    }
    service = OperationsCommandCenterService(
        runtime,
        services["post_ga"],
        services["triage"],
        services["resolution"],
        services["slo"],
        services["capacity"],
        services["continuity"],
        services["provider"],
        services["financial"],
        services["renewal"],
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, services


def _healthy_evidence(root: Path):
    service, services = _service(root)
    post_ga = services["post_ga"]
    _write(
        post_ga.default_baseline_path(),  # type: ignore[attr-defined]
        {
            "valid": True,
            "status": "ready",
            "rollout_percentage": 100,
            "evidence_age_days": 1,
            "warning_count": 0,
        },
    )

    slo = services["slo"]
    _write(
        slo.snapshots_dir / "slo-snapshot.json",  # type: ignore[attr-defined]
        {
            "availability_percent": 99.99,
            "error_budget_remaining_minutes": 43.0,
        },
    )
    _write(
        slo.decisions_dir / "slo-decision.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "decision": "allow",
            "snapshot_filename": "slo-snapshot.json",
        },
    )

    capacity = services["capacity"]
    _write(
        capacity.snapshots_dir / "capacity-snapshot.json",  # type: ignore[attr-defined]
        {"projected_headroom_percent": 38.0, "days_to_saturation": None},
    )
    _write(
        capacity.decisions_dir / "capacity-decision.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "decision": "allow_release",
            "snapshot_filename": "capacity-snapshot.json",
        },
    )

    continuity = services["continuity"]
    _write(
        continuity.results_dir / "continuity-result.json",  # type: ignore[attr-defined]
        {
            "outcome": "passed",
            "actual_restore_minutes": 5,
            "rto_target_minutes": 15,
        },
    )
    _write(
        continuity.attestations_dir / "continuity-attestation.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "status": "verified",
            "result_filename": "continuity-result.json",
        },
    )

    provider = services["provider"]
    _write(
        provider.governance_dir / "provider-governance.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "provider_decisions": [
                {"provider": "Provider A", "decision": "preferred"},
                {"provider": "Provider B", "decision": "approved"},
            ],
        },
    )

    financial = services["financial"]
    _write(
        financial.audits_dir / "financial-audit.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "invoice_count": 2,
            "total_residual_variance": "0.00",
        },
    )

    renewal = services["renewal"]
    _write(
        renewal.renewals_dir / "renewal.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "decision": "renew",
            "metrics": {"open_exception_count": 0, "high_exception_count": 0},
        },
    )
    return service, services


def test_phase80_empty_evidence_is_attention_not_false_healthy(tmp_path: Path) -> None:
    service, _services = _service(tmp_path)
    snapshot = service.snapshot()
    assert snapshot.overall_status == "attention"
    assert snapshot.unknown_count == 7
    assert snapshot.healthy_count == 1  # no unresolved incident case is healthy


def test_phase80_all_verified_domains_are_healthy(tmp_path: Path) -> None:
    service, _services = _healthy_evidence(tmp_path)
    snapshot = service.snapshot(project_id=7)
    assert snapshot.overall_status == "healthy"
    assert snapshot.healthy_count == 8
    assert snapshot.critical_count == 0
    assert snapshot.project_id == 7


def test_phase80_tampered_slo_decision_is_critical(tmp_path: Path) -> None:
    service, services = _healthy_evidence(tmp_path)
    path = services["slo"].decisions_dir / "slo-decision.json"  # type: ignore[attr-defined]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["valid"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = service.snapshot()
    slo = next(item for item in snapshot.domains if item.code == "slo")
    assert slo.status == "critical"
    assert snapshot.overall_status == "critical"


def test_phase80_open_p1_incident_is_critical(tmp_path: Path) -> None:
    service, services = _healthy_evidence(tmp_path)
    _write(
        services["triage"].cases_dir / "triage-case.json",  # type: ignore[attr-defined]
        {"valid": True, "case_id": "case-1", "priority": "P1"},
    )
    snapshot = service.snapshot()
    incidents = next(item for item in snapshot.domains if item.code == "incidents")
    assert incidents.status == "critical"
    assert "P1" in incidents.metric


def test_phase80_verified_closure_removes_incident_from_active_count(tmp_path: Path) -> None:
    service, services = _healthy_evidence(tmp_path)
    _write(
        services["triage"].cases_dir / "triage-case.json",  # type: ignore[attr-defined]
        {"valid": True, "case_id": "case-1", "priority": "P1"},
    )
    _write(
        services["resolution"].closures_dir / "resolution-closure.json",  # type: ignore[attr-defined]
        {"valid": True, "case_id": "case-1", "status": "closed"},
    )
    snapshot = service.snapshot()
    incidents = next(item for item in snapshot.domains if item.code == "incidents")
    assert incidents.status == "healthy"
    assert incidents.metric == "0 active"


def test_phase80_capacity_manual_action_is_warning(tmp_path: Path) -> None:
    service, services = _healthy_evidence(tmp_path)
    path = services["capacity"].decisions_dir / "capacity-decision.json"  # type: ignore[attr-defined]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision"] = "prepare_degraded_mode"
    path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = service.snapshot()
    capacity = next(item for item in snapshot.domains if item.code == "capacity")
    assert capacity.status == "warning"
    assert snapshot.overall_status == "attention"


def test_phase80_provider_restriction_and_billing_residual_surface_risk(tmp_path: Path) -> None:
    service, services = _healthy_evidence(tmp_path)
    _write(
        services["provider"].governance_dir / "provider-governance.json",  # type: ignore[attr-defined]
        {
            "valid": True,
            "provider_decisions": [
                {"provider": "Provider A", "decision": "restricted"},
            ],
        },
    )
    _write(
        services["financial"].audits_dir / "financial-audit.json",  # type: ignore[attr-defined]
        {"valid": True, "invoice_count": 1, "total_residual_variance": "2.50"},
    )
    snapshot = service.snapshot()
    providers = next(item for item in snapshot.domains if item.code == "providers")
    billing = next(item for item in snapshot.domains if item.code == "billing")
    assert providers.status == "critical"
    assert billing.status == "critical"


def test_phase80_export_verifies_and_detects_source_custody_change(tmp_path: Path) -> None:
    service, services = _healthy_evidence(tmp_path)
    path = service.export_snapshot(service.snapshot())
    assert service.verify_snapshot(path)[0]
    source = services["financial"].audits_dir / "financial-audit.json"  # type: ignore[attr-defined]
    source.write_text('{"valid": true, "invoice_count": 99}', encoding="utf-8")
    ok, detail = service.verify_snapshot(path)
    assert not ok
    assert "custody changed" in detail


def test_phase80_source_contract_wires_unified_workspace_and_read_only_cli() -> None:
    root = Path(__file__).resolve().parents[1]
    main_text = (root / "app/gui/main.py").read_text(encoding="utf-8")
    frozen_text = (root / "app/frozen_main.py").read_text(encoding="utf-8")
    service_text = (root / "app/services/operations_command_center_service.py").read_text(
        encoding="utf-8"
    )
    assert "Production Operations Command Center" in main_text
    assert "open_operations_command_center" in main_text
    assert "--operations-command-center-snapshot" in frozen_text
    assert '"read_only": True' in service_text
    assert '"automatic_provider_change": False' in service_text
    assert '"automatic_billing_change": False' in service_text
