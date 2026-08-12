from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.gui.theme import DARK_TOKENS, LIGHT_TOKENS, ThemeManager
from app.models import AppSettings, TTSJob
from app.repositories.voice_repository import VoiceRepository
from app.services.preview_service import PreviewService
from app.services.voice_service import VoiceService


def _clear_qsettings() -> None:
    settings = QSettings("S Talking", "S Talking")
    settings.clear()
    settings.sync()


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path):
    _app()
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    return MainWindow(context)


def _voice_service(tmp_path: Path) -> VoiceService:
    database = Database(tmp_path / "voices.db")
    database.initialize()
    return VoiceService(
        VoiceRepository(database),
        tmp_path / "previews",
        PreviewService(tmp_path / "previews" / "index.json"),
    )


def test_global_provider_model_voice_language_restore(tmp_path: Path) -> None:
    _clear_qsettings()
    settings = QSettings("S Talking", "S Talking")
    settings.setValue("global_settings/provider", "elevenlabs")
    settings.setValue("global_settings/model_id", "model-a")
    settings.setValue("global_settings/voice_id", "voice-a")
    settings.setValue("global_settings/language_code", "sv")
    settings.setValue("global_settings/stability", 0.62)

    window = _window(tmp_path)

    assert window.provider.currentText() == "elevenlabs"
    assert window.current_model_id() == "model-a"
    assert window.voice.text() == "voice-a"
    assert window.current_language_code() == "sv"
    assert window.stability.value() == 62
    window.close()


def test_project_settings_override_and_close_returns_global_fallback(tmp_path: Path) -> None:
    _clear_qsettings()
    settings = QSettings("S Talking", "S Talking")
    settings.setValue("global_settings/provider", "mock")
    settings.setValue("global_settings/model_id", "global-model")
    settings.setValue("global_settings/voice_id", "global-voice")
    settings.setValue("global_settings/language_code", "da")
    window = _window(tmp_path)

    output = tmp_path / "out"
    output.mkdir()
    project_settings = AppSettings(provider="elevenlabs", voice_id="project-voice", model_id="project-model", language_code="en")
    state = window.project_controller.new_project("Project", None, output, project_settings)
    window.apply_project_state(state)

    assert window.provider.currentText() == "elevenlabs"
    assert window.voice.text() == "project-voice"
    assert window.current_model_id() == "project-model"
    assert window.current_language_code() == "en"

    window.close_project()

    assert window.provider.currentText() == "mock"
    assert window.voice.text() == "global-voice"
    assert window.current_model_id() == "global-model"
    assert window.current_language_code() == "da"
    window.close()


def test_voice_browser_favorite_tabs_and_star_preserve_selection(tmp_path: Path) -> None:
    _clear_qsettings()
    _app()
    from app.gui.voice_browser import VoiceBrowserDialog

    service = _voice_service(tmp_path)
    service.repository.upsert(provider="elevenlabs", voice_id="voice-1", name="Beta", language="da")
    service.repository.upsert(provider="elevenlabs", voice_id="voice-2", name="Alpha", language="en")
    dialog = VoiceBrowserDialog(service=service, settings_provider=lambda: AppSettings(provider="elevenlabs", model_id="model-a"))

    dialog.table.selectRow(1)
    selected = dialog.selected_item()
    assert selected is not None
    dialog.toggle_favorite()

    assert dialog.selected_item() is not None
    assert dialog.selected_item().voice_id == selected.voice_id
    assert dialog.table.item(dialog.table.currentRow(), 0).text() == "★"

    dialog.tabs.setCurrentIndex(1)
    assert [dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())] == [selected.name]
    dialog.close()


def test_voice_browser_responsive_and_audio_settings_drive_preview_settings(tmp_path: Path) -> None:
    _clear_qsettings()
    _app()
    from app.gui.voice_browser import VoiceBrowserDialog

    service = _voice_service(tmp_path)
    dialog = VoiceBrowserDialog(service=service, settings_provider=lambda: AppSettings(provider="mock", language_code="da"))
    dialog.resize(1280, 720)
    dialog.show()
    _app().processEvents()
    dialog.setting_sliders["stability"][0].setValue(33)
    dialog.setting_sliders["speed"][0].setValue(100)
    dialog.source_language.setCurrentIndex(dialog.source_language.findData("tr"))
    visible = dialog.preview_settings()

    assert dialog.table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.details_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert not dialog.audio_player.isHidden()
    assert visible.stability == 0.33
    assert visible.speed == 1.2
    assert visible.language_code == "tr"
    dialog.close()


def test_non_modal_report_notification_and_explicit_view(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    _app().processEvents()
    report = window.create_report({"total": 0, "completed": 0, "failed": 0, "skipped": 0})

    window.notify_report_created(report, {"completed": 0, "failed": 0, "skipped": 0})

    assert not window.report_dialogs
    assert not window.report_button.isHidden()
    window.view_latest_report_dialog()
    assert window.report_dialogs
    window.close()


def test_preflight_status_counts_and_warning_startable(tmp_path: Path) -> None:
    window = _window(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "one.wav").write_bytes(b"existing")
    window.out.setText(str(out))
    window.generation_controller.set_jobs([TTSJob(row_number=1, filename="one.wav", text="Hej")])

    state = window.run_preflight()

    assert state.status == "Ready with warnings"
    assert "0 errors" in window.preflight_status.text()
    assert "1 warnings" in window.preflight_status.text()
    assert window.startb.isEnabled()
    window.close()


def test_theme_semantic_tokens_and_live_switch(tmp_path: Path) -> None:
    _clear_qsettings()
    window = _window(tmp_path)

    window.apply_theme("Light")

    assert ThemeManager().current() == "Light"
    assert DARK_TOKENS["app"] == "#0B1220"
    assert LIGHT_TOKENS["primary"] == "#2563EB"
    assert "#F4F7FB" in QApplication.instance().styleSheet()
    window.close()
