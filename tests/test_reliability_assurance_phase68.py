from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from app.config.runtime import RuntimeConfig
from app.models.reliability_assurance import ReliabilityAssuranceRecord
from app.services.reliability_assurance_service import ReliabilityAssuranceService


NOW = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)


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


def _write(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class _FakeEffectivenessService:
    REVIEW_DECISIONS = (
        "continue_monitoring",
        "escalate_prevention",
        "accept_residual_risk",
        "close_effective",
    )

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.root = runtime.artifacts_dir / "prevention-effectiveness"
        self.reviews_dir = self.root / "reviews"
        self.decisions_dir = self.root / "decisions"
        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_dir.mkdir(parents=True, exist_ok=True)

    def verify_review(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "Review is unreadable."
        expected = str(payload.pop("review_sha256", ""))
        if expected != _digest(payload):
            return False, "Review SHA-256 does not match."
        if payload.get("status") != "verified" or payload.get("human_review_completed") is not True:
            return False, "Review is not human verified."
        return True, "Review is intact."

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "Decision is unreadable."
        expected = str(payload.pop("decision_sha256", ""))
        if expected != _digest(payload):
            return False, "Decision SHA-256 does not match."
        if payload.get("human_decision") is not True:
            return False, "Decision lacks human acknowledgement."
        if str(payload.get("decision") or "") not in self.REVIEW_DECISIONS:
            return False, "Decision is invalid."
        review_id = str(payload.get("review_id") or "")
        review_path = self.reviews_dir / f"{review_id}.json"
        review_ok, detail = self.verify_review(review_path)
        if not review_ok:
            return False, detail
        return True, "Decision is intact."

    @staticmethod
    def _read(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def _signed(path: Path, payload: dict[str, object], digest_field: str) -> Path:
    payload[digest_field] = _digest(payload)
    return _write(path, payload)


def _pair(
    predecessor: _FakeEffectivenessService,
    *,
    suffix: str = "alpha",
    source_decision: str = "close_effective",
    age_days: int = 5,
    open_actions: int = 0,
    overdue_actions: int = 0,
    recurrence: int = 0,
    ineffective: int = 0,
) -> tuple[Path, Path]:
    review_id = f"review-{suffix}"
    created_at = (NOW - timedelta(days=age_days)).isoformat()
    review_payload: dict[str, object] = {
        "schema_version": 1,
        "review_id": review_id,
        "snapshot_id": f"snapshot-{suffix}",
        "created_at": created_at,
        "version": "1.0.0",
        "channel": "stable",
        "status": "verified",
        "baseline_id": f"baseline-{suffix}",
        "register_id": f"register-{suffix}",
        "observation_days": 30,
        "metrics": {
            "open_action_count": open_actions,
            "completed_action_count": 2,
            "deferred_action_count": 0,
            "accepted_risk_action_count": 0,
            "overdue_action_count": overdue_actions,
            "recurrent_pattern_count": recurrence,
            "ineffective_pattern_count": ineffective,
        },
        "actions": [],
        "patterns": [],
        "human_review_completed": True,
        "automatic_completion": False,
        "automatic_risk_acceptance": False,
        "automatic_ticket_creation": False,
        "automatic_scheduling": False,
        "automatic_patch": False,
        "automatic_deploy": False,
        "automatic_rollback": False,
        "automatic_restart": False,
        "automatic_publish": False,
        "private_data_included": False,
    }
    review_path = _signed(
        predecessor.reviews_dir / f"{review_id}.json",
        review_payload,
        "review_sha256",
    )
    decision_payload: dict[str, object] = {
        "schema_version": 1,
        "decision_id": f"decision-{suffix}",
        "review_id": review_id,
        "created_at": created_at,
        "version": "1.0.0",
        "channel": "stable",
        "baseline_id": f"baseline-{suffix}",
        "decision": source_decision,
        "rationale": "Human reviewed reliability outcome for governance assurance.",
        "status": "recorded",
        "human_decision": True,
        "automatic_completion": False,
        "automatic_risk_acceptance": False,
        "automatic_ticket_creation": False,
        "automatic_scheduling": False,
        "automatic_patch": False,
        "automatic_deploy": False,
        "automatic_rollback": False,
        "automatic_restart": False,
        "automatic_publish": False,
        "private_data_included": False,
    }
    decision_path = _signed(
        predecessor.decisions_dir / f"{review_id}-decision.json",
        decision_payload,
        "decision_sha256",
    )
    return review_path, decision_path


def _service(root: Path) -> tuple[ReliabilityAssuranceService, _FakeEffectivenessService]:
    runtime = _runtime(root)
    predecessor = _FakeEffectivenessService(runtime)
    service = ReliabilityAssuranceService(
        runtime,
        predecessor,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, predecessor


def test_phase68_verified_closed_pair_is_ready_without_exceptions(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(predecessor)

    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))

    assert snapshot.status == "ready"
    assert snapshot.assurance_allowed
    assert snapshot.verified_pair_count == 1
    assert snapshot.close_effective_count == 1
    assert snapshot.open_exception_count == 0


def test_phase68_monitoring_and_escalation_become_governed_exceptions(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review_a, decision_a = _pair(
        predecessor,
        suffix="monitoring",
        source_decision="continue_monitoring",
        age_days=31,
    )
    review_b, decision_b = _pair(
        predecessor,
        suffix="escalation",
        source_decision="escalate_prevention",
    )

    snapshot = service.snapshot(
        review_paths=(review_a, review_b),
        decision_paths=(decision_a, decision_b),
    )

    assert snapshot.status == "ready_with_exceptions"
    assert snapshot.open_exception_count == 2
    assert snapshot.high_exception_count == 2
    assert {item.category for item in snapshot.exceptions} == {
        "continued_monitoring",
        "prevention_escalation",
    }


def test_phase68_recurrence_and_overdue_actions_create_critical_controls(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(
        predecessor,
        source_decision="continue_monitoring",
        overdue_actions=2,
        recurrence=1,
        ineffective=1,
    )

    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))

    categories = {item.category for item in snapshot.exceptions}
    assert "overdue_preventive_action" in categories
    assert "recurrence_or_ineffectiveness" in categories
    assert snapshot.high_exception_count >= 2


def test_phase68_tampered_or_unpaired_sources_block_assurance(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(predecessor)
    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["baseline_id"] = "tampered"
    _write(review, payload)

    tampered = service.snapshot(review_paths=(review,), decision_paths=(decision,))
    unpaired = service.snapshot(
        review_paths=(tmp_path / "missing-review.json",),
        decision_paths=(decision,),
    )

    assert tampered.status == "blocked"
    assert tampered.rejected_source_count > 0
    assert unpaired.status == "blocked"


def test_phase68_assurance_creation_is_dry_run_without_acknowledgement(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(predecessor)
    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))

    result = service.create_assurance(
        snapshot,
        decision="assure",
        owner="Reliability lead",
        statement="The verified control evidence supports an unqualified assurance decision.",
    )

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"


def test_phase68_unqualified_assurance_is_blocked_by_open_exceptions(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(
        predecessor,
        source_decision="accept_residual_risk",
    )
    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))

    result = service.create_assurance(
        snapshot,
        decision="assure",
        owner="Reliability lead",
        statement="The evidence was reviewed but open exceptions remain under governance.",
        acknowledge=True,
    )

    assert isinstance(result, dict)
    assert result["status"] == "blocked"
    assert "exceptions" in str(result["detail"]).lower()


def test_phase68_exception_assurance_requires_owner_date_and_privacy(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(
        predecessor,
        source_decision="continue_monitoring",
    )
    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))

    missing = service.create_assurance(
        snapshot,
        decision="assure_with_exceptions",
        owner="Reliability lead",
        statement="Monitoring remains open and requires an explicitly governed review cycle.",
        acknowledge=True,
    )
    private = service.create_assurance(
        snapshot,
        decision="assure_with_exceptions",
        owner="Reliability lead",
        statement="Monitoring remains open and requires an explicitly governed review cycle.",
        exception_owner="password=secret",
        next_review_date="2026-08-20",
        acknowledge=True,
    )

    assert isinstance(missing, dict) and missing["status"] == "blocked"
    assert isinstance(private, dict) and private["status"] == "blocked"


def test_phase68_creates_and_verifies_assurance_audit_pack(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(predecessor)
    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))

    result = service.create_assurance(
        snapshot,
        decision="assure",
        owner="Reliability lead",
        statement="The verified evidence supports an unqualified reliability assurance decision.",
        acknowledge=True,
    )

    assert isinstance(result, ReliabilityAssuranceRecord)
    assert result.audit_pack_path.is_file()
    assert result.receipt_path.is_file()
    assert service.verify_attestation(result.attestation_path)[0]
    assert service.verify_audit_pack(result.audit_pack_path, result.receipt_path)[0]
    with zipfile.ZipFile(result.audit_pack_path) as archive:
        assert "manifest.json" in archive.namelist()
        assert "assurance/attestation.json" in archive.namelist()


def test_phase68_tampering_attestation_or_pack_is_detected(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    review, decision = _pair(predecessor)
    snapshot = service.snapshot(review_paths=(review,), decision_paths=(decision,))
    result = service.create_assurance(
        snapshot,
        decision="assure",
        owner="Reliability lead",
        statement="The verified evidence supports an unqualified reliability assurance decision.",
        acknowledge=True,
    )
    assert isinstance(result, ReliabilityAssuranceRecord)

    attestation_payload = json.loads(result.attestation_path.read_text(encoding="utf-8"))
    attestation_payload["decision"] = "withhold_assurance"
    _write(result.attestation_path, attestation_payload)
    assert not service.verify_attestation(result.attestation_path)[0]

    with result.audit_pack_path.open("ab") as handle:
        handle.write(b"tamper")
    assert not service.verify_audit_pack(result.audit_pack_path, result.receipt_path)[0]
