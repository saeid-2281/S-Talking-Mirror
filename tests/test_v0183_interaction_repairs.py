from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog
from app.gui.dialogs.pronunciation_dictionary_dialog import PronunciationDictionaryDialog
from app.gui.icons import ACTION_ICONS
from app.gui.main import MainWindow
from app.models import AppSettings, TTSJob
from app.services.generation_scope_service import GenerationScopeService
from app.services.voice_service import AccountUsage, VoiceCatalog


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path) -> MainWindow:
    app = _app()
    QSettings("S Talking", "S Talking").clear()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    app.processEvents()
    return window


def test_semantic_icon_registry_covers_v0183_actions() -> None:
    required = {
        "provider.accounts",
        "provider.test_connection",
        "provider.browse_voices",
        "provider.replace_key",
        "generation.preflight",
        "pronunciation.import_pls",
        "general.quota",
    }

    assert required.issubset(ACTION_ICONS)
    assert ACTION_ICONS["provider.accounts"] != ACTION_ICONS["provider.test_connection"]
    assert ACTION_ICONS["provider.browse_voices"] != ACTION_ICONS["provider.refresh_models"]
    assert ACTION_ICONS["pronunciation.import_pls"] != ACTION_ICONS["pronunciation.sync"]


def test_generation_scope_natural_sort_and_displayed_range() -> None:
    jobs = [
        TTSJob(row_number=1, filename="file10.wav", text="12345"),
        TTSJob(row_number=2, filename="file2.wav", text="12"),
        TTSJob(row_number=3, filename="file1.wav", text="123"),
    ]
    service = GenerationScopeService()

    sorted_jobs = service.build_plan(jobs, execution_order="filename_asc").jobs
    displayed = service.build_plan(
        jobs,
        scope_mode="display_range",
        execution_order="filename_asc",
        display_range=(1, 2),
    ).jobs

    assert [job.filename for job in sorted_jobs] == ["file1.wav", "file2.wav", "file10.wav"]
    assert [job.filename for job in displayed] == ["file1.wav", "file2.wav"]


def test_quota_shortfall_is_warning_not_blocking(tmp_path: Path, monkeypatch) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = tmp_path / "out"
    output.mkdir()
    settings = AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="eleven_multilingual_v2")
    container.voice_repository.upsert(
        provider="elevenlabs",
        voice_id="voice",
        name="Voice",
        metadata={"compatible_model_ids": ["eleven_multilingual_v2"]},
    )
    catalog = VoiceCatalog(voices=(), models=(), account=AccountUsage("Free", "ok", 99_000, 100_000), refreshed_at="now")
    monkeypatch.setattr(container.preflight_service.voice_service, "cached_catalog", lambda _settings: catalog)

    state = container.preflight_service.run(jobs=[TTSJob(row_number=1, filename="one.mp3", text="x" * 2_000)], settings=settings, output_dir=output)

    assert any(issue.code == "insufficient_quota" and issue.severity == "warning" for issue in state.issues)
    assert state.blocking_errors == 0


def test_provider_accounts_empty_state_and_profiles_visible(tmp_path: Path) -> None:
    app = _app()
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    dialog = ProviderAccountsDialog(container.api_profile_service, container.voice_service, lambda: AppSettings(provider="elevenlabs"))
    dialog.refresh()
    assert dialog.stack.currentWidget() is dialog.empty_state

    first = container.api_profile_service.create_profile("Primary", api_key="sk_one", active=True)
    container.api_profile_service.create_profile("Backup", api_key="sk_two")
    dialog.refresh()
    app.processEvents()

    assert dialog.stack.currentWidget() is dialog.table
    assert dialog.table.rowCount() == 2
    names = {dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())}
    assert names == {"Primary", "Backup"}
    active_rows = [row for row in range(dialog.table.rowCount()) if dialog.table.item(row, 0).text() == "Yes"]
    assert active_rows and dialog.table.item(active_rows[0], 1).text() == first.display_name
    dialog.close()


def test_pronunciation_dictionary_guided_empty_state(tmp_path: Path) -> None:
    _app()
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    dialog = PronunciationDictionaryDialog(container.pronunciation_dictionary_service, lambda: AppSettings(provider="elevenlabs", language_code="da"))

    assert dialog.stack.currentWidget() is dialog.empty_state
    assert "Pronunciation dictionaries" in dialog.findChild(type(dialog.compatibility), "emptyTitle").text()
    assert "Provider: elevenlabs" in dialog.empty_provider_status.text()
    dialog.close()


def test_main_queue_header_sort_and_selection_scope(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.generation_controller.set_jobs([
        TTSJob(row_number=1, filename="file10.wav", text="12345"),
        TTSJob(row_number=2, filename="file2.wav", text="12"),
    ])
    window.render_queue()

    window.queue_header_clicked(1)
    assert window.current_execution_order() == "csv"
    assert window.displayed_queue_jobs()[0].filename == "file2.wav"

    window.table.selectRow(0)
    window.use_selection_as_scope()
    assert window.current_scope_mode() == "selected"
    assert window.generation_controller.generation_jobs()[0].filename == "file2.wav"
    window.close()
