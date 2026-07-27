from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.pronunciation_dictionary_dialog import PronunciationDictionaryDialog
from app.gui.voice_browser import VoiceBrowserDialog
from app.models.domain import AppSettings


def test_voice_browser_has_professional_context_filters_and_recent_tab(qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = VoiceBrowserDialog(
        service=context.voice_service,
        settings_provider=lambda: AppSettings(provider="mock"),
    )

    assert dialog.objectName() == "voiceBrowserDialog"
    assert dialog.findChild(type(dialog.provider_label), "voiceDetailsTitle") is dialog.title
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "All voices",
        "Favorites",
        "Recent",
    ]
    assert dialog.refresh_button.objectName() == "primaryQuietButton"
    assert dialog.favorite_button.objectName() == "favoriteButton"
    dialog.close()


def test_recent_tab_switches_to_recent_sort_without_enabling_favorites(qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = VoiceBrowserDialog(
        service=context.voice_service,
        settings_provider=lambda: AppSettings(provider="mock"),
    )

    dialog.tabs.setCurrentIndex(2)

    assert dialog.favorites.isChecked() is False
    assert dialog.sort.currentData() == "recent"
    dialog.close()


def test_pronunciation_manager_uses_header_and_action_cards(qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = PronunciationDictionaryDialog(
        context.pronunciation_dictionary_service,
        lambda: AppSettings(provider="elevenlabs", language_code="da"),
    )

    assert dialog.objectName() == "pronunciationDictionaryDialog"
    assert dialog.findChild(type(dialog.compatibility), "dictionaryCompatibility") is dialog.compatibility
    assert dialog.findChild(type(dialog.empty_state), "dictionaryHeaderCard") is not None
    assert dialog.findChild(type(dialog.empty_state), "dictionaryActionCard") is not None
    dialog.close()
