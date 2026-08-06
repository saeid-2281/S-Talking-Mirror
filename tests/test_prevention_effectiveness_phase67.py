from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from app.config.runtime import RuntimeConfig
from app.models.prevention_effectiveness import PreventionEffectivenessRecord
from app.services.prevention_effectiveness_service import PreventionEffectivenessService


NOW = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def _runtime(root: Path) -> RuntimeConfig:
    runtime = RuntimeConfig(
        app_root=root,
        data_dir=root / "data",
        database_path=root / "data" / "s_talking.db",
        legacy_database_path=root / "data" / "s-talking.db",
        settings_path=root / "settings" / "settings.json",
        log_dir=root / "logs",
        cache_dir=root / "cache",
        default_output_dir=root / "output",
        reports_dir=root / "reports",
        artifacts_dir=root / "artifacts",
        resource_dir=root,
    )
    runtime.ensure_directories()
    return runtime


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class _FakeResolutionService:
    def __init__(self, root: Path) -> None:
        self.closures_dir = root / "closures"
        self.closures_dir.mkdir(parents=True, exist_ok=True)

    def verify_closure(self, path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "Closure is unreadable."
        expected = str(payload.pop("closure_sha256", ""))
        if expected != _digest(payload):
            return False, "Closure SHA-256 does not match."
        return True, "Closure is intact."


class _FakePreventionService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self.root = runtime.artifacts_dir / "incident-prevention"
        self.baselines_dir = self.root / "baselines"
        self.registers_dir = self.root / "registers"
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        self.registers_dir.mkdir(parents=True, exist_ok=True)
        self.incident_resolution_service = _FakeResolutionService(self.root)

    def verify_baseline(self, path: Path) -> tuple[bool, str]:
        return self._verify_signed(path, "baseline_sha256", "Baseline")

    def verify_register(self, path: Path) -> tuple[bool, str]:
        return self._verify_signed(path, "register_sha256", "Register")

    def default_closure_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self.incident_resolution_service.closures_dir.glob("*.json")))

    def _inspect_closure(
        self,
        path: Path,
        *,
        lookback_days: int,
    ) -> tuple[SimpleNamespace | None, str]:
        ok, detail = self.incident_resolution_service.verify_closure(path)
        if not ok:
            return None, detail
        payload = json.loads(path.read_text(encoding="utf-8"))
        closed_at = datetime.fromisoformat(str(payload["created_at"]))
        age_days = max(0, int((NOW - closed_at).total_seconds() // 86400))
        if age_days > lookback_days:
            return None, "ignored"
        return (
            SimpleNamespace(
                path=path,
                closure_id=payload["closure_id"],
                resolution_id=payload["resolution_id"],
                case_id=payload["case_id"],
                fingerprint=payload["fingerprint"],
                priority=payload["priority"],
                component=payload["component"],
                resolution_type=payload["resolution_type"],
                closed_at=payload["created_at"],
                age_days=age_days,
                sha256=_sha(path),
            ),
            "Closure is intact.",
        )

    @staticmethod
    def _verify_signed(path: Path, digest_field: str, label: str) -> tuple[bool, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, f"{label} is unreadable."
        expected = str(payload.pop(digest_field, ""))
        if expected != _digest(payload):
            return False, f"{label} SHA-256 does not match."
        return True, f"{label} is intact."


def _signed(path: Path, payload: dict[str, object], digest_field: str) -> Path:
    payload[digest_field] = _digest(payload)
    return _write(path, payload)


def _service(
    root: Path,
    *,
    baseline_risk: int = 75,
    baseline_age_days: int = 5,
) -> tuple[PreventionEffectivenessService, Path, Path, _FakePreventionService]:
    runtime = _runtime(root)
    predecessor = _FakePreventionService(runtime)
    baseline_id = "baseline-phase67"
    register_id = "register-phase67"
    created_at = NOW - timedelta(days=baseline_age_days)
    register_payload: dict[str, object] = {
        "schema_version": 1,
        "register_id": register_id,
        "baseline_id": baseline_id,
        "created_at": created_at.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "status": "open",
        "actions": [
            {
                "order": 1,
                "code": "assign_owner",
                "label": "Assign a human owner",
                "owner": "reliability_lead",
                "target_days": 30,
                "pattern_fingerprint": "",
                "automatic": False,
                "status": "open",
                "completed_at": "",
                "completion_evidence": "",
            },
            {
                "order": 2,
                "code": f"pattern_{FINGERPRINT[:12]}",
                "label": "Review recurring queue pattern",
                "owner": "component_owner",
                "target_days": 30,
                "pattern_fingerprint": FINGERPRINT,
                "automatic": False,
                "status": "open",
                "completed_at": "",
                "completion_evidence": "",
            },
        ],
        "human_owner_required": True,
        "human_approval_required": True,
        "automatic_ticket_creation": False,
        "automatic_scheduling": False,
        "automatic_patch": False,
        "automatic_deploy": False,
        "automatic_rollback": False,
        "automatic_restart": False,
        "automatic_publish": False,
        "private_data_included": False,
    }
    register_path = _signed(
        predecessor.registers_dir / f"{baseline_id}-action-register.json",
        register_payload,
        "register_sha256",
    )
    baseline_payload: dict[str, object] = {
        "schema_version": 1,
        "baseline_id": baseline_id,
        "snapshot_id": "snapshot-phase67",
        "created_at": created_at.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "status": "verified",
        "lookback_days": 90,
        "recurrence_threshold": 2,
        "high_risk_threshold": 70,
        "source_closures": [{"filename": "source.json", "size_bytes": 1, "sha256": "b" * 64}],
        "patterns": [
            {
                "fingerprint": FINGERPRINT,
                "component": "queue",
                "resolution_type": "code_fix",
                "occurrence_count": 2,
                "priorities": ["P1"],
                "case_ids": ["case-1", "case-2"],
                "first_closed_at": (created_at - timedelta(days=10)).isoformat(),
                "last_closed_at": created_at.isoformat(),
                "risk_score": baseline_risk,
                "recurring": True,
                "high_risk": baseline_risk >= 70,
            }
        ],
        "metrics": {
            "source_closure_count": 2,
            "pattern_count": 1,
            "recurring_pattern_count": 1,
            "high_risk_pattern_count": 1,
            "open_action_count": 2,
        },
        "action_register": {
            "filename": register_path.name,
            "size_bytes": register_path.stat().st_size,
            "sha256": _sha(register_path),
        },
        "human_review_completed": True,
        "human_owner_required": True,
        "automatic_ticket_creation": False,
        "automatic_scheduling": False,
        "automatic_patch": False,
        "automatic_deploy": False,
        "automatic_rollback": False,
        "automatic_restart": False,
        "automatic_publish": False,
        "private_data_included": False,
    }
    baseline_path = _signed(
        predecessor.baselines_dir / f"{baseline_id}.json",
        baseline_payload,
        "baseline_sha256",
    )
    service = PreventionEffectivenessService(
        runtime,
        predecessor,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, baseline_path, register_path, predecessor


def _closure(
    predecessor: _FakePreventionService,
    *,
    suffix: str,
    age_days: int = 1,
    fingerprint: str = FINGERPRINT,
) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "closure_id": f"closure-{suffix}",
        "resolution_id": f"resolution-{suffix}",
        "case_id": f"case-{suffix}",
        "created_at": (NOW - timedelta(days=age_days)).isoformat(),
        "priority": "P1",
        "component": "queue",
        "resolution_type": "code_fix",
        "fingerprint": fingerprint,
    }
    return _signed(
        predecessor.incident_resolution_service.closures_dir / f"closure-{suffix}.json",
        payload,
        "closure_sha256",
    )


def _attest_all_completed(
    service: PreventionEffectivenessService,
    baseline: Path,
    register: Path,
) -> None:
    for code in ("assign_owner", f"pattern_{FINGERPRINT[:12]}"):
        result = service.create_action_attestation(
            baseline_path=baseline,
            register_path=register,
            action_code=code,
            status="completed",
            owner="Reliability owner",
            evidence_summary="The preventive action was reviewed and independently verified.",
            evidence_reference=f"verification-{code}",
            acknowledge=True,
        )
        assert isinstance(result, Path)


def test_phase67_verified_sources_create_ready_snapshot(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)

    snapshot = service.snapshot(
        baseline_path=baseline,
        register_path=register,
        closure_paths=(),
        observation_days=30,
    )

    assert snapshot.status == "ready"
    assert snapshot.review_allowed
    assert snapshot.open_action_count == 2
    assert snapshot.completed_action_count == 0
    assert snapshot.recurrent_pattern_count == 0
    assert snapshot.patterns[0].effectiveness == "monitoring"


def test_phase67_completed_attestation_updates_action_state(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)

    path = service.create_action_attestation(
        baseline_path=baseline,
        register_path=register,
        action_code="assign_owner",
        status="completed",
        owner="Reliability owner",
        evidence_summary="Human ownership was assigned and independently confirmed.",
        evidence_reference="review-ownership-001",
        acknowledge=True,
    )

    assert isinstance(path, Path)
    assert service.verify_attestation(path)[0]
    snapshot = service.snapshot(baseline_path=baseline, register_path=register)
    assert snapshot.completed_action_count == 1
    assert snapshot.open_action_count == 1


def test_phase67_private_material_is_rejected(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)

    result = service.create_action_attestation(
        baseline_path=baseline,
        register_path=register,
        action_code="assign_owner",
        status="completed",
        owner="Reliability owner",
        evidence_summary="password=secret-value was used during verification.",
        evidence_reference="C:\\Users\\Saeid\\secret.txt",
        acknowledge=True,
    )

    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase67_tampered_attestation_blocks_snapshot(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)
    path = service.create_action_attestation(
        baseline_path=baseline,
        register_path=register,
        action_code="assign_owner",
        status="completed",
        owner="Reliability owner",
        evidence_summary="Human ownership was assigned and independently confirmed.",
        evidence_reference="review-ownership-001",
        acknowledge=True,
    )
    assert isinstance(path, Path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["owner"] = "Changed owner"
    _write(path, payload)

    snapshot = service.snapshot(baseline_path=baseline, register_path=register)

    assert snapshot.status == "blocked"
    assert snapshot.blocker_count == 1
    assert any(gate.code == "attestation_integrity" for gate in snapshot.gates)


def test_phase67_post_baseline_recurrence_is_ineffective(tmp_path: Path) -> None:
    service, baseline, register, predecessor = _service(tmp_path)
    closure = _closure(predecessor, suffix="new", age_days=1)

    snapshot = service.snapshot(
        baseline_path=baseline,
        register_path=register,
        closure_paths=(closure,),
        observation_days=30,
    )

    assert snapshot.status == "ready_with_warnings"
    assert snapshot.verified_closure_count == 1
    assert snapshot.recurrent_pattern_count == 1
    assert snapshot.ineffective_pattern_count == 1
    assert snapshot.patterns[0].effectiveness == "ineffective"


def test_phase67_review_is_dry_run_without_acknowledgement(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)
    snapshot = service.snapshot(baseline_path=baseline, register_path=register)

    result = service.create_review(
        snapshot,
        decision="continue_monitoring",
        rationale="Continue the observation window while action owners complete the register.",
        acknowledge=False,
    )

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"


def test_phase67_effective_closure_requires_completed_actions(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)
    snapshot = service.snapshot(baseline_path=baseline, register_path=register)
    blocked = service.create_review(
        snapshot,
        decision="close_effective",
        rationale="The observation window shows no recurrence and the preventive cycle can close.",
        acknowledge=True,
    )
    assert isinstance(blocked, dict)
    assert blocked["status"] == "blocked"

    _attest_all_completed(service, baseline, register)
    refreshed = service.snapshot(baseline_path=baseline, register_path=register)
    record = service.create_review(
        refreshed,
        decision="close_effective",
        rationale="The completed actions and thirty-day observation show no verified recurrence.",
        acknowledge=True,
    )

    assert isinstance(record, PreventionEffectivenessRecord)
    assert service.verify_review(record.review_path)[0]
    assert service.verify_decision(record.decision_path)[0]


def test_phase67_residual_risk_requires_attestation_and_risk_below_90(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path, baseline_risk=80)
    snapshot = service.snapshot(baseline_path=baseline, register_path=register)
    blocked = service.create_review(
        snapshot,
        decision="accept_residual_risk",
        rationale="A human owner accepts the documented residual risk for continued monitoring.",
        acknowledge=True,
    )
    assert isinstance(blocked, dict)
    assert blocked["status"] == "blocked"

    attestation = service.create_action_attestation(
        baseline_path=baseline,
        register_path=register,
        action_code=f"pattern_{FINGERPRINT[:12]}",
        status="risk_accepted",
        owner="Release owner",
        evidence_summary="Residual risk was reviewed against the verified prevention baseline.",
        acknowledge=True,
    )
    assert isinstance(attestation, Path)
    refreshed = service.snapshot(baseline_path=baseline, register_path=register)
    record = service.create_review(
        refreshed,
        decision="accept_residual_risk",
        rationale="The release owner accepts the documented residual risk with continued monitoring.",
        acknowledge=True,
    )
    assert isinstance(record, PreventionEffectivenessRecord)


def test_phase67_tampering_review_or_decision_is_detected(tmp_path: Path) -> None:
    service, baseline, register, _predecessor = _service(tmp_path)
    snapshot = service.snapshot(baseline_path=baseline, register_path=register)
    record = service.create_review(
        snapshot,
        decision="continue_monitoring",
        rationale="Continue monitoring while the remaining preventive actions stay human controlled.",
        acknowledge=True,
    )
    assert isinstance(record, PreventionEffectivenessRecord)

    review = json.loads(record.review_path.read_text(encoding="utf-8"))
    review["status"] = "changed"
    _write(record.review_path, review)
    assert not service.verify_review(record.review_path)[0]

    decision = json.loads(record.decision_path.read_text(encoding="utf-8"))
    decision["decision"] = "close_effective"
    _write(record.decision_path, decision)
    assert not service.verify_decision(record.decision_path)[0]
