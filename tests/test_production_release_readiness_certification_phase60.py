from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.production_release_certification_service import (
    ProductionReleaseCertificationService,
)


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _evidence(
    tmp_path: Path,
    *,
    passed: int = 841,
    captured_at: str | None = None,
    source_commit: str = "a" * 40,
) -> dict[str, Path]:
    stamp = captured_at or datetime.now(timezone.utc).isoformat()
    return {
        "quality_gate": _write(
            tmp_path / "quality.json",
            {
                "success": True,
                "exit_code": 0,
                "finished_at": stamp,
                "source_commit": source_commit,
                "working_tree_clean": True,
                "steps": {"pytest": {"success": True, "passed": passed}},
            },
        ),
        "ux_certification": _write(
            tmp_path / "ux.json",
            {"status": "certified", "blocker_count": 0, "warning_count": 0, "generated_at": stamp},
        ),
        "security_snapshot": _write(
            tmp_path / "security.json",
            {
                "status": "healthy",
                "blocker_count": 0,
                "warning_count": 0,
                "credential_backend": "windows-credential-manager",
                "captured_at": stamp,
            },
        ),
        "performance_snapshot": _write(
            tmp_path / "performance.json",
            {"status": "healthy", "blocker_count": 0, "warning_count": 0, "captured_at": stamp},
        ),
        "crash_recovery": _write(
            tmp_path / "crash.json",
            {
                "status": "healthy",
                "integrity_failure_count": 0,
                "unacknowledged_count": 0,
                "captured_at": stamp,
            },
        ),
        "final_release": _write(
            tmp_path / "final-release-manifest.json",
            {
                "version": "0.18.2-rc1",
                "channel": "preview",
                "blocker_count": 0,
                "warning_count": 0,
                "generated_at": stamp,
                "artifacts": [{"role": "portable_package", "sha256": "a" * 64}],
            },
        ),
        "update_channel": _write(
            tmp_path / "latest.json",
            {
                "product": "S Talking",
                "channel": "preview",
                "version": "0.18.2-rc1",
                "published_at": stamp,
                "artifacts": [{"role": "portable_package", "sha256": "b" * 64}],
            },
        ),
        "upgrade_backup": _write(
            tmp_path / "upgrade-backup-manifest.json",
            {
                "backup_id": "backup-1",
                "source_version": "0.18.2-rc1",
                "created_at": stamp,
                "files": [{"role": "database", "sha256": "c" * 64}],
            },
        ),
    }


def test_phase60_certifies_complete_evidence_with_explicit_preview_warning(tmp_path: Path) -> None:
    service = ProductionReleaseCertificationService(_runtime(tmp_path))
    snapshot = service.certification_snapshot(
        target_version="1.0.0",
        source_commit="a" * 40,
        expected_test_count=841,
        evidence_paths=_evidence(tmp_path),
    )
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.promotion_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 1
    assert snapshot.observed_test_count == 841
    assert {artifact.role for artifact in snapshot.evidence} == set(service.REQUIRED_ROLES)


def test_phase60_blocks_invalid_target_missing_commit_and_insufficient_tests(tmp_path: Path) -> None:
    service = ProductionReleaseCertificationService(_runtime(tmp_path))
    snapshot = service.certification_snapshot(
        target_version="1.0.0-rc1",
        source_commit="not-a-commit",
        expected_test_count=841,
        evidence_paths=_evidence(tmp_path, passed=840),
    )
    assert snapshot.status == "blocked"
    assert not snapshot.promotion_allowed
    blocked = {gate.gate_id for gate in snapshot.gates if gate.status == "block"}
    assert {"target_version", "source_commit", "evidence_quality_gate"} <= blocked


def test_phase60_missing_or_stale_evidence_is_never_silently_accepted(tmp_path: Path) -> None:
    service = ProductionReleaseCertificationService(_runtime(tmp_path))
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    paths = _evidence(tmp_path, captured_at=old, source_commit="b" * 40)
    paths.pop("upgrade_backup")
    snapshot = service.certification_snapshot(
        source_commit="b" * 40,
        evidence_paths=paths,
        max_evidence_age_days=30,
    )
    assert snapshot.status == "blocked"
    assert any(gate.gate_id == "evidence_upgrade_backup" and gate.status == "block" for gate in snapshot.gates)
    assert any(gate.status == "warn" and "older than" in gate.detail for gate in snapshot.gates)


def test_phase60_rejects_secret_bearing_structured_evidence(tmp_path: Path) -> None:
    service = ProductionReleaseCertificationService(_runtime(tmp_path))
    paths = _evidence(tmp_path, source_commit="c" * 40)
    payload = json.loads(paths["security_snapshot"].read_text(encoding="utf-8"))
    payload["api_key"] = "sk-this-must-never-enter-an-attestation"
    _write(paths["security_snapshot"], payload)
    snapshot = service.certification_snapshot(
        source_commit="c" * 40,
        evidence_paths=paths,
    )
    gate = next(gate for gate in snapshot.gates if gate.gate_id == "evidence_security_snapshot")
    assert gate.status == "block"
    assert "secret-bearing" in gate.detail
    assert "sk-this" not in json.dumps(snapshot.to_dict())


def test_phase60_attestation_is_tamper_evident_and_uses_only_file_names(tmp_path: Path) -> None:
    service = ProductionReleaseCertificationService(_runtime(tmp_path))
    snapshot = service.certification_snapshot(
        source_commit="d" * 40,
        evidence_paths=_evidence(tmp_path, source_commit="d" * 40),
    )
    attestation = service.write_attestation(snapshot)
    ok, detail = service.verify_attestation(attestation)
    assert ok, detail
    text = attestation.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    document = json.loads(text)
    document["payload"]["target_version"] = "9.9.9"
    attestation.write_text(json.dumps(document), encoding="utf-8")
    ok, detail = service.verify_attestation(attestation)
    assert not ok
    assert "SHA-256" in detail


def test_phase60_promotion_plan_requires_acknowledgement_and_never_changes_source(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    release_file = runtime.app_root / "app" / "release.py"
    release_file.parent.mkdir(parents=True, exist_ok=True)
    release_file.write_text('VERSION = "0.18.2-rc1"\n', encoding="utf-8")
    original = release_file.read_bytes()
    service = ProductionReleaseCertificationService(runtime)
    snapshot = service.certify_and_write(
        source_commit="e" * 40,
        evidence_paths=_evidence(tmp_path, source_commit="e" * 40),
    )
    dry_run = service.create_promotion_plan(snapshot, acknowledge=False)
    assert dry_run["status"] == "dry_run"
    assert not list(service.plan_dir.glob("*.json"))
    prepared = service.create_promotion_plan(snapshot, acknowledge=True)
    assert prepared["status"] == "prepared"
    assert Path(str(prepared["path"])).exists()
    assert release_file.read_bytes() == original
    plan_text = Path(str(prepared["path"])).read_text(encoding="utf-8")
    assert '"automatic_publish": false' in plan_text
    assert '"automatic_version_change": false' in plan_text


def test_phase60_export_summary_is_privacy_safe_and_verifiable(tmp_path: Path) -> None:
    service = ProductionReleaseCertificationService(_runtime(tmp_path))
    snapshot = service.certify_and_write(
        source_commit="f" * 40,
        evidence_paths=_evidence(tmp_path, source_commit="f" * 40),
    )
    attestation, summary = service.export_snapshot(snapshot)
    ok, detail = service.verify_attestation(attestation)
    assert ok, detail
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["private_data_included"] is False
    assert payload["attestation_file"] == attestation.name
    assert len(payload["attestation_sha256"]) == 64
    assert str(tmp_path) not in summary.read_text(encoding="utf-8")


def test_phase60_cli_script_dialog_container_and_release_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    service = (root / "app" / "services" / "production_release_certification_service.py").read_text(encoding="utf-8")
    dialog = (root / "app" / "gui" / "dialogs" / "production_release_certification_dialog.py").read_text(encoding="utf-8")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "production-certification.ps1").read_text(encoding="utf-8")
    docs = (root / "docs" / "PRODUCTION_RELEASE_READINESS_PHASE60.md").read_text(encoding="utf-8")
    assert "--production-certification" in frozen
    assert "--verify-production-attestation" in frozen
    assert "--acknowledge-production-plan" in frozen
    assert "never changes app.release" in service
    assert "Production release readiness & 1.0 certification" in dialog
    assert "Production Release Certification" in main
    assert "production_release_certification_service" in container
    assert "--refresh-production-evidence" in script
    assert "manual stable-channel publication" in docs
