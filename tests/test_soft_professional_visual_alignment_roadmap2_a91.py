from __future__ import annotations

import inspect
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.main_workspace_modernization import MainWorkspaceModernizer, main_workspace_stylesheet
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


BASELINE_A9 = "25a3d5d1f83e6bc1241dc5c6466610cc06571853"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    container = create_service_container(runtime)
    return MainWindow(create_application_context(container))


def test_a91_keeps_soft_professional_palette_and_theme_root_authority() -> None:
    assert ACTIVE_CONCEPT == "soft_professional"
    light = palette_for(is_dark=False)
    assert light.canvas == "#F7F6F3"
    assert light.surface == "#FFFFFF"
    assert light.surface_secondary == "#F1F0EC"
    assert light.primary == "#5271C6"
    stylesheet = main_workspace_stylesheet(is_dark=False)
    assert "Roadmap 2 A9.1" in stylesheet
    assert "QMainWindow" not in stylesheet


def test_a91_reserves_filled_primary_for_launch_and_softens_queue_actions() -> None:
    stylesheet = main_workspace_stylesheet(is_dark=False)
    assert "QFrame#generationActionBar QPushButton#startGenerationButton" in stylesheet
    assert "background:#5271C6" in stylesheet
    assert "QPushButton#queuePrimaryAction" in stylesheet
    assert "background:#ECF0FB" in stylesheet
    assert "color:#5271C6" in stylesheet


def test_a91_unifies_empty_state_instead_of_three_block_panels() -> None:
    stylesheet = main_workspace_stylesheet(is_dark=False)
    assert "QFrame#emptyState, QWidget#emptyState" in stylesheet
    assert "QFrame#emptyState QLabel, QWidget#emptyState QLabel" in stylesheet
    assert "background:transparent; border:0; color:#626762" in stylesheet
    assert "border-radius:14px" in stylesheet


def test_a91_softens_queue_chrome_and_strengthens_control_readability() -> None:
    stylesheet = main_workspace_stylesheet(is_dark=False)
    assert "QFrame#queueCommandBar" in stylesheet
    assert "background:#F1F0EC; border:0; border-radius:12px" in stylesheet
    assert "QLineEdit#queueSearch" in stylesheet
    assert "min-height:30px" in stylesheet
    assert "QLabel#queueCommandSectionLabel" in stylesheet


def test_a91_aligns_toolbar_tabs_provider_and_inspector_with_desktop_saas_hierarchy() -> None:
    stylesheet = main_workspace_stylesheet(is_dark=False)
    assert "QToolBar#mainToolbar" in stylesheet
    assert "padding:2px 8px; spacing:4px" in stylesheet
    assert "QTabWidget#leftWorkspaceTabs QTabBar::tab" in stylesheet
    assert "padding:8px 11px" in stylesheet
    assert "QFrame#providerSection, QFrame#collapsibleSection" in stylesheet
    assert "QFrame#selectedRowCard" in stylesheet


def test_a91_modernizer_remains_presentation_only() -> None:
    source = inspect.getsource(MainWorkspaceModernizer)
    forbidden = (
        "run_preflight(",
        "start_generation(",
        "generation_controller.start(",
        "provider.setCurrent",
        "model.setCurrent",
        "voice.setText",
        "language.setCurrent",
        "apply_smart_provider_routing_recommendation(",
        "detect_language(",
    )
    for token in forbidden:
        assert token not in source
    assert "_apply_soft_professional_geometry" in source
    assert "visualAlignment" in source


def test_a91_runtime_applies_calm_geometry_without_breaking_a9_contracts(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.application_shell.property("visualAlignment") == "soft-professional"
    assert window.queue_workspace.property("visualAlignment") == "soft-professional"
    assert window.provider_panel.property("visualAlignment") == "soft-professional"
    assert window.selected_row_panel.property("visualAlignment") == "soft-professional"

    margins = window.queue_workspace.heading.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (12, 8, 10, 8)
    assert window.queue_workspace.heading.layout().spacing() == 8
    assert window.queue_workspace.command_layout.spacing() == 6
    assert window.generation_status_strip.layout().spacing() == 8

    assert window.empty_state.maximumWidth() == 680
    assert window.empty_state.minimumHeight() >= 240
    assert window.empty_state.maximumHeight() == 360
    assert window.empty_state.property("visualRole") == "calm-empty-state"

    # restore_layout_state() applies a legacy density pass after A9.1 install.
    # The integration hook must restore the Soft Professional geometry.
    window.apply_density("compact")
    margins = window.queue_workspace.heading.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (12, 8, 10, 8)
    window.apply_density("comfortable")
    margins = window.queue_workspace.heading.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (12, 8, 10, 8)

    for mode in ("compact", "standard", "wide"):
        window.main_workspace_modernizer.apply_responsive_mode(mode)
        assert 270 <= window.left_dock.minimumWidth() <= 300
        assert window.left_dock.maximumWidth() <= 300
        margins = window.queue_workspace.heading.layout().contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (12, 8, 10, 8)
    window.close()


def test_a91_wide_operator_visibility_and_standard_more_contract_survive(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    assert not window.use_selection_scope_button.isHidden()
    assert not window.skip_menu_button.isHidden()
    assert not window.reset_menu_button.isHidden()
    assert not window.clear_completed_button.isHidden()
    assert not window.output_menu_button.isHidden()
    assert window.queue_more_actions_button.isHidden()

    window.main_workspace_modernizer.apply_responsive_mode("standard")
    assert window.use_selection_scope_button.isHidden()
    assert not window.queue_more_actions_button.isHidden()
    window.close()
