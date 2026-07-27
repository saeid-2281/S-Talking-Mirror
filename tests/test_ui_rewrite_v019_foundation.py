from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow


def test_provider_workspace_is_extracted_and_structured(qt_app, tmp_path: Path) -> None:
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    qt_app.processEvents()

    assert window.provider_scroll.widget() is window.provider_panel
    assert window.provider_panel.objectName() == "providerPanel"
    assert window.provider_panel.findChild(type(window.connection_status), "connectionStatus") is window.connection_status
    assert window.connection_status.minimumHeight() == 52
    assert window.connection_status.maximumHeight() == 52
    assert window.api_profile.minimumWidth() >= 180
    assert window.model.minimumWidth() >= 180
    assert window.voice.minimumWidth() >= 180
    assert window.account_manager_button.toolTip() == "Provider accounts"
    assert set(window.provider_sections) == {
        "Provider & Account",
        "Voice & Model",
        "Audio Settings",
        "Pronunciation",
        "Advanced",
    }


def test_main_window_no_longer_contains_monolithic_provider_builder() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "ProviderWorkspaceBuilder(self).build()" in source
    assert "sb=QFrame(); self.provider_panel=sb" not in source
