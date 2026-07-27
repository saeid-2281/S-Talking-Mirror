from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog
from app.gui.main import MainWindow
from app.bootstrap import create_application_context
from app.models.domain import AppSettings


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_provider_accounts_uses_tabs_splitter_and_readable_details(tmp_path: Path) -> None:
    app = _app()
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    container.api_profile_service.create_profile("Primary production account", api_key="sk_primary", active=True)
    container.api_profile_service.create_profile("Backup account", api_key="sk_backup")

    dialog = ProviderAccountsDialog(
        container.api_profile_service,
        container.voice_service,
        lambda: AppSettings(provider="elevenlabs"),
    )
    dialog.show()
    app.processEvents()

    assert dialog.tabs.count() == 2
    assert dialog.tabs.tabText(0) == "Accounts"
    assert dialog.tabs.tabText(1) == "Failover"
    assert dialog.account_splitter.orientation() == Qt.Horizontal
    assert dialog.table.rowCount() == 2
    assert dialog.details_panel.minimumWidth() >= 270
    assert dialog.table.minimumWidth() >= 560
    assert dialog.details_name.text() in {"Primary production account", "Backup account"}
    assert dialog.details_status.minimumHeight() >= 48
    dialog.close()


def test_main_provider_profile_row_no_longer_contains_failover_combo(tmp_path: Path) -> None:
    app = _app()
    runtime = RuntimeConfig.from_root(tmp_path)
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    app.processEvents()

    assert window.api_profile.parentWidget() is not None
    assert window.failover.parentWidget() is not window.api_profile.parentWidget()
    assert window.connection_status.minimumHeight() == 52
    assert window.connection_status.maximumHeight() == 52
    window.close()
