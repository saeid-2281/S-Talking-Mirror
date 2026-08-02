from __future__ import annotations

import json
from pathlib import Path

from app.gui.dialogs.generation_launch_receipt_dialog import GenerationLaunchReceiptDialog
from app.models import AppSettings
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


def _plan(**overrides) -> BatchGenerationPlan:
    values = dict(
        provider="elevenlabs",
        model="model-a",
        files=10,
        characters=10_000,
        provider_requests=10,
        estimated_cost=1.0,
        currency="USD",
        price_per_million_characters=100.0,
        pricing_source="test-rate",
        estimated_duration_seconds=120.0,
        estimated_completion_at="2026-08-02T12:02:00+00:00",
        throughput_confidence="high",
        limiting_factor="characters",
        historical_session_count=6,
        quota_remaining=20_000,
        quota_shortfall=0,
        quota_usage_percent=50.0,
        max_queue_cost=2.0,
        budget_usage_percent=50.0,
        risk_level="low",
        reasons=("All checks are within limits.",),
        scenarios=(
            GenerationPlanScenario("base", "Base", 0, 10, 10_000, 10, 1.0, 120.0),
            GenerationPlanScenario(
                "expected", "Expected retries", 20, 10, 12_000, 12, 1.2, 144.0
            ),
            GenerationPlanScenario(
                "stress", "Stress test", 25, 10, 12_500, 12, 1.25, 150.0
            ),
        ),
    )
    values.update(overrides)
    return BatchGenerationPlan(**values)


def _state(**overrides) -> PreflightState:
    values = dict(
        total_jobs=10,
        valid_jobs=10,
        estimated_files=10,
        estimated_characters=10_000,
        estimated_provider_requests=10,
        estimated_duration_seconds=120.0,
        estimated_cost=1.0,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="preflight-revision",
        settings_revision="settings-revision",
        generation_plan=_plan(),
    )
    values.update(overrides)
    return PreflightState(**values)


def _write_receipt(
    reports_dir: Path,
    *,
    project_name: str = "Phase 36 Project",
    provider: str = "elevenlabs",
    model: str = "model-a",
    state: PreflightState | None = None,
) -> Path:
    coordinator = GenerationConfirmationCoordinator()
    current_state = state or _state(
        generation_plan=_plan(provider=provider, model=model)
    )
    settings = AppSettings(
        provider=provider,
        api_key="must-never-be-serialized",
        model_id=model,
        voice_id="voice-a",
    )
    confirmation = coordinator.evaluate(current_state, settings)
    return coordinator.write_receipt(
        confirmation,
        current_state,
        settings,
        reports_dir=reports_dir,
        project_name=project_name,
        output_dir=reports_dir / "output" / project_name,
        acknowledged_codes=confirmation.required_acknowledgements,
    )


def _legacy_receipt(reports_dir: Path, project_name: str = "Legacy Project") -> Path:
    folder = reports_dir / project_name / "launches" / "legacy-launch"
    folder.mkdir(parents=True)
    path = folder / "generation-launch.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-08-01T10:00:00+00:00",
                "project_name": project_name,
                "launch_fingerprint": "legacy-fingerprint",
                "preflight_status": "Ready",
                "review_status": "ready",
                "acknowledged_codes": [],
                "required_acknowledgements": [],
                "scope": {
                    "files": 2,
                    "characters": 200,
                    "provider_requests": 2,
                    "existing_outputs": 0,
                },
                "settings": {
                    "provider": "mock",
                    "model_id": "mock-model",
                    "voice_id": "mock-voice",
                },
                "output_directory": str(reports_dir / "legacy-output"),
                "generation_plan": {
                    "risk_level": "low",
                    "estimated_cost": 0,
                    "currency": "USD",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    path.with_name("generation-launch.md").write_text("# Legacy\n", encoding="utf-8")
    return path


def test_phase36_new_receipts_have_verified_integrity_and_no_secrets(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    path = _write_receipt(reports_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    receipt = GenerationLaunchReceiptService(reports_dir).load(path)

    assert payload["schema_version"] == 2
    assert payload["receipt_id"].startswith("launch-")
    assert payload["integrity"]["algorithm"] == "sha256"
    assert receipt.integrity_status == "verified"
    assert receipt.integrity_ok is True
    assert "must-never-be-serialized" not in path.read_text(encoding="utf-8")
    assert "Integrity: sha256" in path.with_name("generation-launch.md").read_text(
        encoding="utf-8"
    )


def test_phase36_modified_receipt_is_detected_as_integrity_mismatch(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    path = _write_receipt(reports_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scope"]["characters"] = 999_999
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    receipt = GenerationLaunchReceiptService(reports_dir).load(path)

    assert receipt.integrity_status == "mismatch"
    assert receipt.integrity_ok is False
    assert receipt.requires_attention is True
    assert "no longer matches" in receipt.integrity_message


def test_phase36_legacy_receipts_remain_readable(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    path = _legacy_receipt(reports_dir)

    receipt = GenerationLaunchReceiptService(reports_dir).load(path)

    assert receipt.schema_version == 1
    assert receipt.project_name == "Legacy Project"
    assert receipt.provider == "mock"
    assert receipt.files == 2
    assert receipt.integrity_status == "legacy"
    assert receipt.integrity_ok is True


def test_phase36_unreadable_receipt_does_not_break_archive_scan(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    _write_receipt(reports_dir, project_name="Healthy Project")
    broken = reports_dir / "Broken Project" / "launches" / "broken"
    broken.mkdir(parents=True)
    (broken / "generation-launch.json").write_text("{broken", encoding="utf-8")

    receipts = GenerationLaunchReceiptService(reports_dir).list_receipts()

    assert len(receipts) == 2
    assert {item.integrity_status for item in receipts} == {"verified", "unreadable"}
    unreadable = next(item for item in receipts if item.integrity_status == "unreadable")
    assert unreadable.project_name == "Broken Project"


def test_phase36_receipt_filters_cover_project_provider_risk_and_search(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    first = _write_receipt(
        reports_dir,
        project_name="Alpha Project",
        provider="elevenlabs",
        model="alpha-model",
    )
    _write_receipt(
        reports_dir,
        project_name="Beta Project",
        provider="openai",
        model="beta-model",
        state=_state(
            generation_plan=_plan(
                provider="openai",
                model="beta-model",
                risk_level="high",
                quota_shortfall=2_000,
                reasons=("Quota is short by 2,000 characters.",),
            )
        ),
    )
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    fingerprint_fragment = first_payload["launch_fingerprint"][:12]
    service = GenerationLaunchReceiptService(reports_dir)

    assert len(service.list_receipts(project_name="Alpha Project")) == 1
    assert len(service.list_receipts(provider="openai")) == 1
    assert len(service.list_receipts(risk_level="high")) == 1
    assert len(service.list_receipts(search="beta-model")) == 1
    assert len(service.list_receipts(search=fingerprint_fragment)) == 1


def test_phase36_summary_and_exports_are_secret_free(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    verified_path = _write_receipt(reports_dir, project_name="Export Project")
    legacy_path = _legacy_receipt(reports_dir)
    verified_payload = json.loads(verified_path.read_text(encoding="utf-8"))
    verified_payload["scope"]["files"] = 12
    verified_payload["integrity"]["digest"] = GenerationLaunchReceiptService.canonical_digest(
        verified_payload
    )
    verified_path.write_text(json.dumps(verified_payload, indent=2), encoding="utf-8")
    service = GenerationLaunchReceiptService(reports_dir)
    records = [service.load(verified_path), service.load(legacy_path)]

    summary = service.summary(records)
    json_path, csv_path = service.export(records, tmp_path / "exports")
    exported = json_path.read_text(encoding="utf-8") + csv_path.read_text(
        encoding="utf-8-sig"
    )

    assert summary.receipt_count == 2
    assert summary.verified_count == 1
    assert summary.legacy_count == 1
    assert summary.total_files == 14
    assert "must-never-be-serialized" not in exported
    assert "api_key" not in exported
    assert "integrity_status" in exported


def test_phase36_receipt_dialog_renders_archive_metrics_and_details(
    qt_app, tmp_path: Path
) -> None:
    reports_dir = tmp_path / "reports"
    _write_receipt(reports_dir, project_name="Current Project")
    _legacy_receipt(reports_dir)
    opened: list[Path] = []
    copied: list[Path] = []
    dialog = GenerationLaunchReceiptDialog(
        GenerationLaunchReceiptService(reports_dir),
        project_name="all-projects",
        export_dir=tmp_path / "exports",
        open_path=lambda path: opened.append(path),
        copy_path=lambda path: copied.append(path),
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.objectName() == "generationLaunchReceiptDialog"
    assert dialog.table.rowCount() == 2
    assert dialog.metric_values["receipts"].text() == "2"
    assert dialog.metric_values["verified"].text() == "1"
    assert dialog.metric_values["legacy"].text() == "1"
    dialog.table.selectRow(0)
    qt_app.processEvents()
    assert "Integrity:" in dialog.details.toPlainText()
    dialog.open_json()
    dialog.copy_receipt_path()
    assert opened and opened[0].name == "generation-launch.json"
    assert copied and copied[0].name == "generation-launch.json"
    exported = dialog.export_filtered()
    assert exported is not None and all(path.exists() for path in exported)
    dialog.close()


def test_phase36_receipt_dialog_filters_current_project_and_integrity(
    qt_app, tmp_path: Path
) -> None:
    reports_dir = tmp_path / "reports"
    _write_receipt(reports_dir, project_name="Current Project")
    _legacy_receipt(reports_dir)
    dialog = GenerationLaunchReceiptDialog(
        GenerationLaunchReceiptService(reports_dir),
        project_name="Current Project",
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.current_project_only.isChecked() is True
    assert dialog.table.rowCount() == 1
    dialog.current_project_only.setChecked(False)
    verified_index = dialog.integrity_filter.findData("verified")
    dialog.integrity_filter.setCurrentIndex(verified_index)
    qt_app.processEvents()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "Verified"
    dialog.search.setText("does-not-exist")
    qt_app.processEvents()
    assert dialog.table.rowCount() == 0
    assert dialog.export_button.isEnabled() is False
    dialog.close()
