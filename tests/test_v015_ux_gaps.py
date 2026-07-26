from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog
from app.gui.dialogs.pronunciation_dictionary_dialog import PronunciationDictionaryDialog
from app.gui.main import MainWindow
from app.models.api_profile import ApiProfileFailoverMode, FailoverSettings
from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_dictionary import PronunciationDictionary, PronunciationRule
from app.services.api_profile_service import ApiProfileService
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.report_service import ReportService
from app.services.queue_service import QueueService
from app.services.secure_credentials import SecureCredentialStore


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _profile_service(tmp_path: Path) -> ApiProfileService:
    return ApiProfileService(tmp_path / "api-profiles.json", SecureCredentialStore(tmp_path / "credentials"))


def test_provider_profile_crud_unique_priority_active_and_credential_delete(tmp_path: Path) -> None:
    service = _profile_service(tmp_path)
    first = service.create_profile("Production", api_key="sk_ONE", active=True)
    second = service.create_profile("Production", api_key="sk_TWO")

    assert second.display_name == "Production 2"
    assert service.active_profile("elevenlabs").profile_id == first.profile_id
    service.move_profile(second.profile_id, -1)
    assert service.list_profiles("elevenlabs")[0].profile_id == second.profile_id
    service.set_active(second.profile_id)
    assert service.active_profile("elevenlabs").profile_id == second.profile_id
    service.set_enabled(second.profile_id, False)
    assert service.get_profile(second.profile_id).enabled is False
    service.remove_profile(second.profile_id)
    assert service.api_key_for(second.profile_id) is None


def test_provider_profile_no_plaintext_secret_leakage(tmp_path: Path) -> None:
    service = _profile_service(tmp_path)
    service.create_profile("Production", api_key="sk_SECRET", active=True)

    metadata = (tmp_path / "api-profiles.json").read_text(encoding="utf-8")
    summary = service.safe_summary()

    assert "sk_SECRET" not in metadata
    assert "sk_SECRET" not in summary
    assert "Saved key" in summary


def test_failover_settings_and_preview(tmp_path: Path) -> None:
    service = _profile_service(tmp_path)
    first = service.create_profile("Primary", api_key="sk_ONE", active=True)
    backup = service.create_profile("Backup", api_key="sk_TWO")
    service.save_failover_settings(
        "elevenlabs",
        FailoverSettings(
            mode=ApiProfileFailoverMode.AUTO,
            max_switches_per_run=3,
            sequence_mode="manual",
            manual_sequence=[first.profile_id, backup.profile_id],
            allow_unknown_quota_override=True,
        ),
    )

    restored = service.failover_settings("elevenlabs")
    preview = service.failover_preview(
        provider="elevenlabs",
        current_profile_id=first.profile_id,
        trigger_reason="insufficient_quota",
    )

    assert restored.mode == ApiProfileFailoverMode.AUTO
    assert restored.max_switches_per_run == 3
    assert restored.sequence_mode == "manual"
    assert restored.allow_unknown_quota_override is True
    assert preview["next_eligible_account"] == "Backup"


def test_provider_accounts_dialog_responsive_and_running_change_protection(tmp_path: Path, monkeypatch) -> None:
    _app()
    service = _profile_service(tmp_path)
    profile = service.create_profile("Production", api_key="sk_ONE", active=True)
    dialog = ProviderAccountsDialog(
        service,
        voice_service=object(),
        settings_provider=lambda: AppSettings(provider="elevenlabs", api_key="sk_ONE"),
        generation_active=lambda: True,
    )
    dialog.show()
    _app().processEvents()
    dialog.table.selectRow(0)

    monkeypatch.setattr("app.gui.dialogs.provider_accounts_dialog.QMessageBox.warning", lambda *args, **kwargs: None)
    dialog.toggle_enabled()

    assert dialog.width() >= 900
    assert dialog.height() >= 560
    assert service.get_profile(profile.profile_id).enabled is True
    dialog.close()


def test_pronunciation_dictionary_local_metadata_validation_export_and_active(tmp_path: Path) -> None:
    service = PronunciationDictionaryService(tmp_path / "dicts")
    dictionary = service.create(
        "Danish",
        language_code="da",
        version_id="v1",
        rules=[
            PronunciationRule("mad", "mað", "alias", "da"),
            PronunciationRule("tak", "tag", "alias", "da"),
        ],
    )
    service.set_active(dictionary.dictionary_id, language_code="da")
    metadata = service.export_metadata(dictionary.dictionary_id, tmp_path / "dictionary.json")
    pls = service.export_pls(dictionary.dictionary_id, tmp_path / "dictionary.pls")

    summary = service.list_dictionaries(language_code="da")[0]
    assert summary.active is True
    assert summary.rule_count == 2
    assert json.loads(metadata.read_text(encoding="utf-8"))["name"] == "Danish"
    assert "<alias>mað</alias>" in pls.read_text(encoding="utf-8")


def test_pronunciation_dictionary_conflict_and_phoneme_capability(tmp_path: Path) -> None:
    service = PronunciationDictionaryService(tmp_path / "dicts")
    dictionary = PronunciationDictionary(
        dictionary_id="dict",
        name="Danish",
        language_code="da",
        rules=[
            PronunciationRule("mad", "one", "alias", "da"),
            PronunciationRule("mad", "two", "alias", "da"),
        ],
    )
    phoneme = PronunciationDictionary(
        dictionary_id="phoneme",
        name="Danish phoneme",
        language_code="da",
        rules=[PronunciationRule("mad", "mat", "phoneme", "da", alphabet="ipa")],
    )

    try:
        service.validate_rules(dictionary)
    except ValueError as exc:
        assert "Conflicting pronunciation rules" in str(exc)
    else:
        raise AssertionError("Conflicting rules should be rejected.")
    try:
        service.validate_rules(phoneme, model_id="eleven_multilingual_v2")
    except ValueError as exc:
        assert "Phoneme rule is not supported" in str(exc)
    else:
        raise AssertionError("Unsupported phoneme rules should be rejected.")
    assert service.validate_rules(phoneme, model_id="eleven_v3") == []


def test_pronunciation_dictionary_dialog_responsive(tmp_path: Path) -> None:
    _app()
    service = PronunciationDictionaryService(tmp_path / "dicts")
    service.create("Danish", rules=[PronunciationRule("mad", "mað")])
    dialog = PronunciationDictionaryDialog(service, lambda: AppSettings(provider="elevenlabs", model_id="eleven_multilingual_v2"))
    dialog.show()
    _app().processEvents()

    assert dialog.width() >= 940
    assert dialog.height() >= 560
    from PySide6.QtCore import Qt

    assert dialog.dictionary_table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.rule_table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    dialog.close()


def test_main_panel_profile_sync_and_preflight_invalidation(tmp_path: Path) -> None:
    _app()
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    profile = context.api_profile_service.create_profile("Production", api_key="sk_PROFILE", active=True)
    window = MainWindow(context)

    assert window.active_api_profile_id() == profile.profile_id
    assert window.key.text() == "sk_PROFILE"
    window.preflight_service.latest = object()
    window.provider_accounts_changed()
    assert window.preflight_service.latest is None
    window.close()


def test_report_records_dictionary_and_override_without_text_change(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = ReportService(runtime)
    settings = AppSettings(
        provider="elevenlabs",
        voice_id="voice",
        model_id="model",
        language_code="da",
        active_pronunciation_dictionary_id="dict",
        pronunciation_dictionary_locators=[{"pronunciation_dictionary_id": "dict", "version_id": "v1"}],
    )
    job = TTSJob(row_number=1, filename="one.mp3", text="mad", pronunciation_override="dictionary_disabled")
    report = service.create_generation_report(
        project=None,
        settings=settings,
        jobs=[job],
        output_dir=tmp_path,
        summary={"completed": 0, "failed": 0, "skipped": 0},
        started_at=datetime.now(timezone.utc),
    )

    csv_text = (report.report_dir / "jobs.csv").read_text(encoding="utf-8")
    assert "dictionary_disabled" in csv_text
    assert "mad" in csv_text
    assert "Udtal dette" not in csv_text


def test_job_pronunciation_override_applied_from_settings_without_text_change() -> None:
    job = TTSJob(row_number=7, filename="seven.mp3", text="en ø")
    settings = AppSettings(provider="elevenlabs", job_pronunciation_overrides={7: "dictionary_disabled"})

    restored = QueueService().sync_project_jobs(None, [job], settings=settings)

    assert restored[0].pronunciation_override == "dictionary_disabled"
    assert restored[0].text == "en ø"
