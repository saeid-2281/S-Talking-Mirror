from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QGridLayout, QLabel

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.provider_controls import ProviderOverviewCard


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase31_provider_overview_is_structured_and_readable(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert isinstance(window.provider_overview, ProviderOverviewCard)
    assert window.provider_overview.objectName() == "providerOverviewCard"
    assert window.provider_overview.name_label.text()
    assert window.provider_overview.status_badge.objectName() == "providerReadinessBadge"
    assert window.provider_overview.profile_label.text()
    assert window.provider_overview.quota_label.text()
    assert isinstance(window.provider_overview.badge_host.layout(), QGridLayout)
    assert window.provider_overview.badge_host.layout().columnCount() == 3


def test_phase31_mock_provider_hides_irrelevant_credential_and_effect_rows(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.provider.setCurrentText("mock")
    qt_app.processEvents()

    assert window.provider_field_rows["api_profile"].isHidden() is True
    assert window.provider_field_rows["api_key"].isHidden() is True
    assert window.provider_field_rows["piper"].isHidden() is True
    assert window.provider_field_rows["stability"].isHidden() is True
    assert window.provider_overview.mode_label.text() == "Local / offline provider"
    assert window.provider_overview.profile_label.text() == "No credential required"


def test_phase31_elevenlabs_reveals_provider_specific_controls(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.provider.setCurrentText("elevenlabs")
    qt_app.processEvents()

    assert window.provider_field_rows["api_profile"].isHidden() is False
    assert window.provider_field_rows["api_key"].isHidden() is False
    assert window.provider_field_rows["stability"].isHidden() is False
    assert window.provider_field_rows["similarity"].isHidden() is False
    assert window.provider_field_rows["failover"].isHidden() is False
    assert window.provider_field_rows["piper"].isHidden() is True
    assert "profile or API key" in window.provider_overview.next_step_label.text()


def test_phase31_piper_reveals_local_model_without_cloud_credentials(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.provider.setCurrentText("piper")
    qt_app.processEvents()

    assert window.provider_field_rows["piper"].isHidden() is False
    assert window.provider_field_rows["api_profile"].isHidden() is True
    assert window.provider_field_rows["api_key"].isHidden() is True
    assert window.provider_overview.mode_label.text() == "Local / offline provider"


def test_phase31_connection_status_updates_readiness_badge(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.set_provider_status("Connected: provider ready")
    qt_app.processEvents()
    assert window.provider_overview.status_badge.text() == "Connected: provider ready"
    assert window.provider_overview.status_badge.property("tone") == "success"

    window.set_provider_status("Connection failed: invalid credential")
    qt_app.processEvents()
    assert window.provider_overview.status_badge.property("tone") == "error"
    assert "Review the credential" in window.provider_overview.next_step_label.text()


def test_phase31_provider_sections_include_context_descriptions(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    for section in window.provider_sections.values():
        assert isinstance(section.description_label, QLabel)
        assert section.description_label.text().strip()
        assert section.description_label.wordWrap() is True


def test_phase31_collapsed_section_summary_tracks_voice_and_profile(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.voice.setText("danish-voice")
    window.provider_sections["Voice & Model"].set_expanded(False)
    window.refresh_provider_workspace_summary()

    assert "danish-voice" in window.provider_sections["Voice & Model"].header.text()
