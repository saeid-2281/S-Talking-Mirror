from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QLabel,
    QSplitter,
    QToolButton,
    QWidget,
)

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.visual_fidelity_hardening import VisualFidelityHardener


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_a111_scope_is_presentation_only_and_installed_after_a11() -> None:
    source = inspect.getsource(MainWindow.build)
    module_source = inspect.getsource(VisualFidelityHardener)

    assert "VisualFidelityHardener(self)" in source
    assert "visual_fidelity_hardener.install()" in source
    assert "start_generation" not in module_source
    assert "run_preflight" not in module_source
    assert "provider_changed" not in module_source
    assert "setCurrentText" not in module_source
    assert "database" not in module_source.casefold()


def test_a111_toolbar_forces_one_canonical_icon_source_and_size(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    hardener = window.visual_fidelity_hardener

    assert window.main_toolbar.iconSize() == QSize(20, 20)
    assert window.main_toolbar.property("visualFidelityIcons") == "canonical"
    for action_name, icon_name in hardener.TOOLBAR_ICON_MAP.items():
        action = window.actions_by_name[action_name]
        assert not action.icon().isNull()
        assert action.property("visualFidelityIcon") == icon_name
        assert action.icon().actualSize(QSize(20, 20)).width() <= 20
        assert action.icon().actualSize(QSize(20, 20)).height() <= 20
    window.close()


def test_a111_toolbar_buttons_share_aligned_geometry(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    buttons = window.main_toolbar.findChildren(QToolButton)

    assert buttons
    assert all(button.iconSize() == QSize(20, 20) for button in buttons)
    assert all(button.minimumHeight() >= 32 for button in buttons)
    assert all(button.maximumHeight() <= 34 for button in buttons)
    assert all(button.property("visualFidelityAlignment") == "toolbar" for button in buttons)
    window.close()


def test_a111_metric_cards_keep_same_soft_radius_when_filter_state_changes(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    card = window.cards["files"]

    assert card.objectName() == "metricPill"
    assert card.property("visualFidelityRadius") == 12
    assert 'QFrame#metricPill[active="true"]' in card.styleSheet()
    assert "border-radius: 12px" in card.styleSheet()

    card.set_active(True)
    qt_app.processEvents()
    assert card.property("active") is True
    assert "border-radius: 12px" in card.styleSheet()

    card.set_active(False)
    qt_app.processEvents()
    assert card.property("active") is False
    assert "border-radius: 12px" in card.styleSheet()
    window.close()


def test_a111_all_operational_metric_cards_share_identical_geometry(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    expected = {"files", "pending", "running", "done", "failed", "quota", "eta"}

    for key in expected:
        card = window.cards[key]
        assert card.property("visualFidelityRadius") == 12
        assert card.minimumHeight() >= 34
        assert card.maximumHeight() <= 42
        assert card.styleSheet() == VisualFidelityHardener.METRIC_STYLE
    window.close()


def test_a111_generation_monitor_gets_full_historical_usable_width(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    monitor_index = next(
        index
        for index in range(window.right_tabs.count())
        if window.right_tabs.tabText(index) == "Generation Monitor"
    )
    window.right_tabs.setCurrentIndex(monitor_index)

    # The historical API contract remains 290px. A11.1 must improve the
    # visible monitor by resizing the actual active dock, not by changing the
    # public minimumWidth() contract used by older tests/integrations.
    assert 280 <= window.monitor_dock.minimumWidth() <= 300

    window.visual_fidelity_hardener.refresh_monitor()
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.maximumWidth() <= 340
    assert window.monitor_dock.property("visualFidelityMonitor") is True
    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    assert window.monitor_scroll.minimumWidth() == 0
    assert window.monitor_sections.tabBar().usesScrollButtons() is True
    window.close()


def test_a111_monitor_content_can_shrink_without_horizontal_clipping(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.visual_fidelity_hardener.refresh_monitor()
    panel = window.monitor_scroll.widget()

    assert panel is not None
    assert panel.minimumWidth() == 0
    assert (
        window.monitor_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    for button in panel.findChildren(QAbstractButton):
        assert button.minimumWidth() == 0 or button.objectName() in {
            "monitorPrimaryAction",
        }
    window.close()


def test_a111_provider_accounts_details_receive_readable_splitter_geometry(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    dialog = window.open_provider_accounts()
    qt_app.processEvents()
    window.visual_fidelity_hardener.polish_dialog(dialog)
    qt_app.processEvents()

    splitter = dialog.findChild(QSplitter, "providerAccountsSplitter")
    details = dialog.findChild(QWidget, "providerAccountDetails")

    assert dialog.property("visualFidelityProviderAccounts") is True
    assert dialog.minimumWidth() >= 1160
    assert dialog.minimumHeight() >= 720
    assert splitter is not None
    assert details is not None
    assert details.minimumWidth() >= 420
    assert splitter.childrenCollapsible() is False
    assert int(splitter.property("visualFidelityDetailsWidth")) >= 420
    dialog.close()
    window.close()


def test_a111_provider_account_detail_actions_are_not_crushed(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    dialog = window.open_provider_accounts()
    qt_app.processEvents()
    window.visual_fidelity_hardener.polish_dialog(dialog)

    details = dialog.findChild(QWidget, "providerAccountDetails")
    assert details is not None
    buttons = details.findChildren(QAbstractButton)
    assert buttons
    assert all(button.minimumHeight() >= 34 for button in buttons)
    assert all(button.minimumWidth() >= 78 for button in buttons)
    dialog.close()
    window.close()


def test_a111_provider_overview_accepts_long_state_without_horizontal_overflow(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    overview = window.provider_overview
    window.set_provider_status("Provider account state changed.")
    window.visual_fidelity_hardener.refresh_provider_overview()
    qt_app.processEvents()

    assert overview.property("visualFidelityProviderOverview") is True
    assert overview.minimumWidth() == 0
    for label in overview.findChildren(QLabel):
        assert label.minimumWidth() == 0
        if len(label.text().strip()) > 22:
            assert label.wordWrap() is True
    window.close()


def test_a111_provider_overview_long_buttons_use_elision_and_full_tooltip(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    overview = window.provider_overview

    probe = QToolButton(overview)
    probe.setText("Provider account state changed and requires attention")
    probe.show()
    window.visual_fidelity_hardener.refresh_provider_overview()

    assert probe.minimumWidth() == 0
    assert probe.property("visualFidelityFullText")
    assert probe.property("visualFidelityElidedText")
    assert probe.toolTip() == "Provider account state changed and requires attention"
    assert "…" in probe.text() or len(probe.text()) < len(probe.toolTip())
    probe.deleteLater()
    window.close()



def test_a111_delete_on_close_non_provider_dialog_has_no_deferred_polish(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    dialog.setWindowTitle("A11.1 report-lifetime probe")
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    dialog.show()
    qt_app.processEvents()
    dialog.close()

    for _ in range(4):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()

    # Reaching this point without a deleted-wrapper RuntimeError is the
    # regression contract. Generic report dialogs are not A11.1 targets.
    assert window.visual_fidelity_hardener._installed is True
    window.close()

def test_a111_preserves_a11_q2_theme_and_authority_contracts() -> None:
    theme_source = inspect.getsource(MainWindow.apply_theme)
    preferences_source = inspect.getsource(MainWindow.apply_interface_preferences)
    responsive_source = inspect.getsource(MainWindow._apply_responsive_workspace)

    assert "application.setPalette(palette)" in theme_source
    assert "properties_changed=previous.stylesheet_properties()!=value.stylesheet_properties()" in preferences_source
    assert "self.setStyleSheet(self.theme_manager.stylesheet" in preferences_source
    assert "self.right_dock.setMaximumWidth(340)" in responsive_source
    assert "visual_fidelity_hardener.refresh_main_window()" in responsive_source
