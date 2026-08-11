from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.release import SCHEMA_VERSION
from app.services.product_ux_audit_service import ProductUXAuditService


def _runtime(tmp_path: Path) -> RuntimeConfig:
    data = tmp_path / "data"
    return RuntimeConfig(
        app_root=tmp_path,
        data_dir=data,
        database_path=data / "s_talking.db",
        legacy_database_path=data / "s-talking.db",
        settings_path=tmp_path / "settings.json",
        log_dir=tmp_path / "logs",
        cache_dir=tmp_path / "cache",
        default_output_dir=tmp_path / "output",
        reports_dir=tmp_path / "reports",
        artifacts_dir=tmp_path / "artifacts",
        resource_dir=tmp_path,
    )


def _service(tmp_path: Path, source_root: Path | None = None) -> ProductUXAuditService:
    return ProductUXAuditService(
        _runtime(tmp_path),
        source_root=source_root or Path.cwd(),
        now=lambda: datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
    )


def test_a1_has_fixed_ten_core_product_journeys(tmp_path: Path) -> None:
    service = _service(tmp_path)
    specs = service.journey_specs()
    assert len(specs) == 10
    assert tuple(item.journey_id for item in specs) == (
        "first_run",
        "provider_setup",
        "voice_discovery",
        "text_preparation",
        "queue_planning",
        "preflight_approval",
        "live_generation",
        "recovery_resume",
        "audio_review_export",
        "settings_accessibility",
    )


def test_a1_assessment_is_deterministic_for_same_source_and_commit(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.assess(source_commit="bb26e31781c689655b17b8a752ff7c3f40ce2095")
    second = service.assess(source_commit="bb26e31781c689655b17b8a752ff7c3f40ce2095")
    assert first.to_dict() == second.to_dict()


def test_a1_current_product_has_no_required_structural_journey_gap(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).assess(source_commit="baseline")
    assert snapshot.blocker_count == 0
    assert snapshot.overall_score >= 70


def test_a1_baseline_produces_evidence_driven_product_opportunities(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).assess(source_commit="baseline")
    assert snapshot.opportunity_count >= 1
    assert snapshot.backlog
    assert all(item.priority in {1, 2} for item in snapshot.backlog)


def test_a1_first_run_identifies_resumable_onboarding_opportunity(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).assess(source_commit="baseline")
    first_run = next(item for item in snapshot.journeys if item.journey_id == "first_run")
    gap_codes = {item.code for item in first_run.evidence if item.status == "missing"}
    assert "first_run_state" in gap_codes


def test_a1_assessment_does_not_create_report_directory(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert not service.root.exists()
    service.assess(source_commit="baseline")
    assert not service.root.exists()


def test_a1_explicit_export_creates_tamper_evident_snapshot(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.assess(source_commit="baseline")
    path = service.export_snapshot(snapshot)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["snapshot_sha256"]
    assert payload["document_schema_version"] == 1
    ok, detail = service.verify_snapshot(path)
    assert ok, detail


def test_a1_snapshot_verification_detects_tampering(tmp_path: Path) -> None:
    service = _service(tmp_path)
    path = service.export_snapshot(service.assess(source_commit="baseline"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["overall_score"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    ok, detail = service.verify_snapshot(path)
    assert not ok
    assert "digest mismatch" in detail


def test_a1_safety_contract_preserves_provider_and_generation_authority() -> None:
    contract = ProductUXAuditService.safety_contract()
    assert contract["read_only_assessment"] is True
    assert contract["automatic_provider_switch"] is False
    assert contract["automatic_catalog_refresh"] is False
    assert contract["automatic_generation_start"] is False
    assert contract["automatic_generation_restart"] is False
    assert contract["automatic_cross_provider_failover"] is False
    assert contract["automatic_database_write"] is False
    assert contract["automatic_network_probe"] is False


def test_a1_does_not_change_database_schema() -> None:
    assert SCHEMA_VERSION == 23


def test_a1_service_has_no_network_client_dependency() -> None:
    source = Path("app/services/product_ux_audit_service.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import httpx" not in source
    assert "urllib.request" not in source
    assert ".synthesize(" not in source
    assert ".refresh(" not in source


def test_a1_service_is_wired_into_container_and_application_context() -> None:
    container = Path("app/container.py").read_text(encoding="utf-8")
    bootstrap = Path("app/bootstrap.py").read_text(encoding="utf-8")
    assert "product_ux_audit_service: ProductUXAuditService" in container
    assert "product_ux_audit_service = ProductUXAuditService(config)" in container
    assert "product_ux_audit_service: ProductUXAuditService" in bootstrap
    assert "product_ux_audit_service=services.product_ux_audit_service" in bootstrap


def test_a1_product_experience_report_entry_is_explicit() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "Product Experience" in source
    assert "Product UX Audit / Workflow Baseline" in source
    assert "def open_product_ux_audit" in source
    assert "ProductUXAuditDialog" in source


def test_a1_product_ux_audit_is_available_from_command_palette() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "Reports: Product UX Audit / Workflow Baseline" in source


def test_a1_dialog_does_not_export_on_open() -> None:
    source = Path("app/gui/dialogs/product_ux_audit_dialog.py").read_text(encoding="utf-8")
    init_body = source.split("def __init__", 1)[1].split("def _build", 1)[0]
    assert "export_snapshot" not in init_body
    assert "self.refresh_view()" in init_body


def test_a1_backlog_required_gaps_sort_before_optional_opportunities(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    service = _service(tmp_path, source_root=source)
    snapshot = service.assess(source_commit="fixture")
    priorities = [item.priority for item in snapshot.backlog]
    assert priorities == sorted(priorities)
    assert priorities and priorities[0] == 1


def test_a1_preserves_phase112_ga_boundary_source() -> None:
    source = Path("app/services/provider_ga_certification_service.py").read_text(encoding="utf-8")
    assert "automatic_cross_provider_failover" in source
    assert '"human_release_promotion_required": True' in source
    assert "EXPECTED_BUILTIN_PROVIDER_IDS" in source


def test_a1_documentation_declares_a2_as_next_product_phase() -> None:
    docs = Path("docs/PRODUCT_UX_AUDIT_WORKFLOW_BASELINE_ROADMAP2_A1.md").read_text(encoding="utf-8")
    assert "A2 — First-run / Onboarding Experience" in docs
    assert "Database schema remains 23" in docs
    assert "No hidden cross-provider failover" in docs
