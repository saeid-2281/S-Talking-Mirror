from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.gui.dialogs.generation_launch_guard_policy_dialog import (
    GenerationLaunchGuardPolicyDialog,
)
from app.gui.dialogs.generation_launch_guard_profile_dialog import (
    GenerationLaunchGuardProfileDialog,
    GenerationLaunchGuardProfileEditorDialog,
)
from app.models import AppSettings
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


def _dispose_dialog(qt_app: QApplication, dialog: QDialog | None) -> None:
    if dialog is None:
        return
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def _plan() -> BatchGenerationPlan:
    return BatchGenerationPlan(
        provider="mock",
        model="model-a",
        files=2,
        characters=2_000,
        provider_requests=2,
        estimated_cost=0.2,
        currency="USD",
        price_per_million_characters=100.0,
        pricing_source="phase41-test",
        estimated_duration_seconds=20.0,
        estimated_completion_at="2026-08-03T11:00:00+00:00",
        throughput_confidence="high",
        limiting_factor="characters",
        historical_session_count=4,
        quota_remaining=10_000,
        quota_shortfall=0,
        quota_usage_percent=20.0,
        max_queue_cost=1.0,
        budget_usage_percent=20.0,
        risk_level="low",
        reasons=("Ready",),
        scenarios=(
            GenerationPlanScenario("base", "Base", 0, 2, 2_000, 2, 0.2, 20.0),
            GenerationPlanScenario("expected", "Expected", 10, 2, 2_200, 2, 0.22, 22.0),
            GenerationPlanScenario("stress", "Stress", 25, 2, 2_500, 3, 0.25, 25.0),
        ),
    )


def _state() -> PreflightState:
    return PreflightState(
        total_jobs=2,
        valid_jobs=2,
        estimated_files=2,
        estimated_characters=2_000,
        estimated_provider_requests=2,
        estimated_duration_seconds=20.0,
        estimated_cost=0.2,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="phase41-preflight",
        settings_revision="phase41-settings",
        generation_plan=_plan(),
    )


def _settings() -> AppSettings:
    return AppSettings(
        provider="mock",
        api_key="must-never-be-serialized",
        model_id="model-a",
        voice_id="voice-a",
        language_code="da",
        file_extension=".mp3",
        max_retries=3,
        delay_seconds=0.5,
        skip_existing=True,
        overwrite_existing=False,
        generation_scope="pending",
        execution_order="source",
    )


def test_phase41_builtin_profiles_and_default_are_stable(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")

    profiles = service.list_guard_policy_profiles()

    assert [item.profile_id for item in profiles[:4]] == [
        "balanced",
        "experimental",
        "provider-migration",
        "strict-production",
    ]
    assert all(item.built_in for item in profiles[:4])
    assert service.default_guard_policy_profile_id() == "balanced"
    inherited = service.guard_policy("New Project")
    assert inherited.profile_id == "balanced"
    assert inherited.mode == "warn"
    assert inherited.version == 0


def test_phase41_custom_profile_round_trip_export_import_is_secret_free(tmp_path: Path) -> None:
    source = GenerationLaunchReceiptService(tmp_path / "source")
    saved = source.save_guard_policy_profile(
        name="Controlled migration",
        description="Allow provider work while protecting output and integrity.",
        mode="warn",
        protected_categories=("Output policy", "Integrity"),
    )
    export_path = source.export_guard_policy_profiles(tmp_path / "profiles.json")
    target = GenerationLaunchReceiptService(tmp_path / "target")

    imported = target.import_guard_policy_profiles(export_path)
    exported_text = export_path.read_text(encoding="utf-8")

    assert imported and imported[0].profile_id == saved.profile_id
    assert target.guard_policy_profile(saved.profile_id) is not None
    assert "must-never-be-serialized" not in exported_text
    assert "api_key" not in exported_text


def test_phase41_applying_profile_versions_policy_and_preserves_history(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")

    first = service.apply_guard_policy_profile(
        "Production Project",
        "strict-production",
        locked=False,
        updated_by="Release lead",
    )
    second = service.apply_guard_policy_profile(
        "Production Project",
        "experimental",
        locked=False,
        updated_by="Release lead",
    )
    history = service.guard_policy_history("Production Project")

    assert first.version == 1
    assert second.version == 2
    assert second.profile_id == "experimental"
    assert [item.version for item in history] == [2, 1]
    assert all(item.action == "profile_applied" for item in history)


def test_phase41_locked_policy_rejects_changes_until_explicit_unlock(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    locked = service.apply_guard_policy_profile(
        "Locked Project",
        "strict-production",
        locked=True,
    )

    try:
        service.set_guard_policy(
            "Locked Project",
            mode="warn",
            protected_categories=("Integrity",),
        )
    except ValueError as exc:
        assert "locked" in str(exc).casefold()
    else:
        raise AssertionError("Locked policy change should fail.")

    unlocked = service.set_guard_policy_lock("Locked Project", False, updated_by="Owner")
    changed = service.apply_guard_policy_profile(
        "Locked Project",
        "balanced",
        updated_by="Owner",
    )

    assert locked.locked is True
    assert unlocked.locked is False
    assert changed.version == 3
    assert changed.profile_id == "balanced"


def test_phase41_default_profile_initializes_new_projects_without_mutating_existing(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    existing = service.apply_guard_policy_profile("Existing Project", "balanced")

    service.set_default_guard_policy_profile("strict-production")
    inherited = service.guard_policy("Future Project")
    unchanged = service.guard_policy("Existing Project")

    assert inherited.profile_id == "strict-production"
    assert inherited.mode == "enforce"
    assert inherited.version == 0
    assert unchanged.profile_id == existing.profile_id == "balanced"
    assert unchanged.version == 1


def test_phase41_receipt_records_policy_profile_version_lock_and_integrity(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    service = GenerationLaunchReceiptService(reports)
    service.apply_guard_policy_profile(
        "Receipt Project",
        "strict-production",
        locked=True,
        updated_by="Release lead",
    )
    coordinator = GenerationConfirmationCoordinator()
    confirmation = coordinator.evaluate(
        _state(),
        _settings(),
        receipt_service=service,
        project_name="Receipt Project",
        output_dir=reports / "audio",
    )
    path = coordinator.write_receipt(
        confirmation,
        _state(),
        _settings(),
        reports_dir=reports,
        project_name="Receipt Project",
        output_dir=reports / "audio",
        receipt_service=service,
    )

    receipt = service.load(path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert receipt.guard_policy_profile_id == "strict-production"
    assert receipt.guard_policy_version == 1
    assert receipt.guard_policy_locked is True
    assert receipt.integrity_status == "verified"
    assert payload["guard_policy"] == {
        "profile_id": "strict-production",
        "version": 1,
        "locked": True,
    }
    assert "must-never-be-serialized" not in path.read_text(encoding="utf-8")


def test_phase41_policy_dialog_applies_profile_unlocks_and_shows_history(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    service.apply_guard_policy_profile("Dialog Project", "strict-production", locked=True)
    dialog = GenerationLaunchGuardPolicyDialog(service, "Dialog Project")
    dialog.show()
    qt_app.processEvents()

    assert dialog.objectName() == "generationLaunchGuardPolicyDialog"
    assert dialog.lock_policy.isChecked() is True
    assert dialog.save_button.isEnabled() is False
    assert "v1" in dialog.history_view.toPlainText()
    dialog.lock_policy.setChecked(False)
    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData("balanced"))
    dialog.apply_selected_profile()
    dialog.updated_by.setText("Policy owner")
    saved = dialog.save_policy()

    assert saved is not None
    assert saved.profile_id == "balanced"
    assert saved.locked is False
    assert saved.version == 2
    _dispose_dialog(qt_app, dialog)


def test_phase41_profile_manager_creates_applies_defaults_and_imports(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    manager = GenerationLaunchGuardProfileDialog(
        service,
        project_name="Managed Project",
        export_dir=tmp_path / "exports",
    )
    manager.show()
    qt_app.processEvents()

    editor = GenerationLaunchGuardProfileEditorDialog(service, manager)
    editor.show()
    qt_app.processEvents()
    editor.name_edit.setText("Focused output")
    editor.description_edit.setPlainText("Protect output policy and integrity for controlled exports.")
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("warn"))
    for category, box in editor.category_boxes.items():
        box.setChecked(category in {"Output policy", "Integrity"})
    saved = editor.save_profile()
    assert saved is not None
    manager.refresh()
    row = next(index for index, item in enumerate(manager.profiles) if item.profile_id == saved.profile_id)
    manager.table.selectRow(row)
    manager.lock_project.setChecked(True)

    assert manager.set_selected_default() is not None
    assert manager.apply_selected() is not None
    export_path = manager.export_profiles(tmp_path / "exported.json")
    imported = manager.import_profiles(export_path)
    policy = service.guard_policy("Managed Project")

    assert service.default_guard_policy_profile_id() == saved.profile_id
    assert policy.profile_id == saved.profile_id
    assert policy.locked is True
    assert imported
    _dispose_dialog(qt_app, editor)
    _dispose_dialog(qt_app, manager)
