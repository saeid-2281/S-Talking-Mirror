from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.main_workspace_modernization import MainWorkspaceModernizer, main_workspace_stylesheet
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT


BASELINE_A81 = "2749a4fe1fe3a19a5342bbd428d2a9270fcfcb35"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    container = create_service_container(runtime)
    return MainWindow(create_application_context(container))


def test_a9_soft_professional_direction_and_root_palette_boundary() -> None:
    assert ACTIVE_CONCEPT == "soft_professional"
    light = main_workspace_stylesheet(is_dark=False)
    assert "Roadmap 2 A9" in light
    assert "QWidget#applicationShell" in light
    assert "QMainWindow" not in light


def test_a9_modernizer_is_presentation_only_and_has_no_automatic_authority() -> None:
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


def test_a9_main_installs_structural_modernizer_and_theme_overlay() -> None:
    source = inspect.getsource(MainWindow)
    assert "self.main_workspace_modernizer=MainWorkspaceModernizer(self)" in source
    assert "self.main_workspace_modernizer.install()" in source
    assert "main_workspace_stylesheet(is_dark=is_dark,concept_key=ACTIVE_CONCEPT)" in source


def test_a9_existing_focus_paths_reveal_progressive_disclosures() -> None:
    source = inspect.getsource(MainWindow)
    assert "main_workspace_modernizer.reveal_workflow(True)" in source
    assert "main_workspace_modernizer.reveal_batch_planning(True)" in source
    assert source.count("main_workspace_modernizer.reveal_provider_insights(True)") >= 2


def test_a9_primary_generation_strip_moves_above_workspace(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    layout = window.application_shell.root_layout
    assert layout.indexOf(window.generation_status_strip) < layout.indexOf(window.main_splitter)
    assert layout.indexOf(window.activity_center) > layout.indexOf(window.main_splitter)
    assert window.generation_status_strip.property("workspaceRole") == "primary-command"
    window.close()


def test_a9_toolbar_removes_duplicate_generation_chrome_not_actions(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    for name in ("Start Generation", "Pause/Resume", "Stop Generation", "Run Preflight"):
        action = window.actions_by_name[name]
        assert action.isVisible()
        toolbar_widget = window.main_toolbar.widgetForAction(action)
        assert toolbar_widget is not None
        assert toolbar_widget.isHidden()
    window.close()


def test_a9_provider_insights_are_progressive_and_explicitly_revealable(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.provider_insights_toggle.objectName() == "providerInsightsDisclosure"
    assert window.provider_intelligence.isHidden()
    assert window.smart_provider_routing.isHidden()
    window.main_workspace_modernizer.reveal_provider_insights(True)
    assert not window.provider_intelligence.isHidden()
    assert not window.smart_provider_routing.isHidden()
    assert window.provider_insights_toggle.isChecked()
    window.close()


def test_a9_queue_uses_header_disclosures_for_workflow_and_batch(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.queue_workflow_toggle.objectName() == "queueWorkflowDisclosure"
    assert window.queue_batch_toggle.objectName() == "queueBatchDisclosure"
    assert window.generation_journey.isHidden()
    assert window.queue_batch_operations.isHidden()
    assert window.queue_workspace.range_host.isHidden()
    window.main_workspace_modernizer.reveal_workflow(True)
    window.main_workspace_modernizer.reveal_batch_planning(True)
    assert not window.generation_journey.isHidden()
    assert not window.queue_batch_operations.isHidden()
    assert not window.queue_workspace.range_host.isHidden()
    window.close()


def test_a9_queue_command_center_prioritizes_core_controls_and_more(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("standard")
    assert not window.queue_search.isHidden()
    assert not window.queue_filter.isHidden()
    assert not window.source_filter.isHidden()
    assert not window.scope_selector.isHidden()
    assert not window.order_selector.isHidden()
    assert not window.dry_run_button.isHidden()
    assert not window.retry_menu_button.isHidden()
    assert not window.queue_more_actions_button.isHidden()
    assert window.queue_workspace.action_layout.indexOf(window.queue_more_actions_button) >= 0
    assert window.use_selection_scope_button.isHidden()
    assert window.skip_menu_button.isHidden()
    assert window.reset_menu_button.isHidden()
    assert window.clear_completed_button.isHidden()
    assert window.output_menu_button.isHidden()
    window.close()


def test_a9_removes_redundant_context_metrics_and_footer_chrome(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.project_context_widget.context_label.isHidden()
    assert window.cards["chars"].isHidden()
    assert window.cards["skipped"].isHidden()
    assert not window.cards["files"].isHidden()
    assert window.queue_workspace.footer.isHidden()
    assert window.empty_state.maximumWidth() == 680
    assert window.empty_state.minimumHeight() >= 220
    window.close()


def test_a9_integrates_docks_and_reapplies_soft_workspace_widths(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.left_dock.titleBarWidget().objectName() == "integratedDockTitle"
    assert window.right_dock.titleBarWidget().objectName() == "integratedDockTitle"
    window.queue_workspace.set_responsive_mode("standard", force=True)
    window.main_workspace_modernizer.apply_responsive_mode("standard")
    assert 280 <= window.left_dock.minimumWidth() <= 300
    assert window.left_dock.maximumWidth() <= 328
    assert 290 <= window.right_dock.minimumWidth() <= 310
    assert window.right_dock.maximumWidth() <= 328
    window.close()


def test_a9_queue_focus_badge_reuses_existing_state_without_new_authority(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    state = SimpleNamespace(scope_label="Selected rows", preflight_status="Passed", generation_active=False)
    window.main_workspace_modernizer.refresh_generation_state(state)
    assert window.queue_focus_badge.text() == "Ready to launch"
    assert "Selected rows" in window.queue_focus_badge.toolTip()
    active = SimpleNamespace(scope_label="Entire queue", preflight_status="Passed", generation_active=True)
    window.main_workspace_modernizer.refresh_generation_state(active)
    assert window.queue_focus_badge.text() == "Generation active"
    window.close()

def test_a9_wide_mode_restores_full_historical_operator_actions(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    for widget in (
        window.use_sort_button,
        window.use_selection_scope_button,
        window.skip_menu_button,
        window.reset_menu_button,
        window.clear_completed_button,
        window.output_menu_button,
    ):
        assert not widget.isHidden()
    assert window.queue_more_actions_button.isHidden()
    window.main_workspace_modernizer.apply_responsive_mode("standard")
    assert not window.queue_more_actions_button.isHidden()
    window.close()


def test_a9_provider_dock_respects_historical_300px_readability_cap(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    for mode in ("compact", "standard", "wide"):
        window.main_workspace_modernizer.apply_responsive_mode(mode)
        assert 270 <= window.left_dock.minimumWidth() <= 300
        assert window.left_dock.maximumWidth() <= 300
    window.close()

