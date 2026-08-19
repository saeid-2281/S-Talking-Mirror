from __future__ import annotations

import inspect
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.generation_launch_dialog import GenerationLaunchDialog
from app.gui.main import MainWindow
from app.gui.widgets.queue_workspace import QueueAccordionStack
from app.models import AppSettings
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightIssue, PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return MainWindow(create_application_context(create_service_container(runtime)))


def _plan() -> BatchGenerationPlan:
    return BatchGenerationPlan(
        provider="elevenlabs",
        model="model-a",
        files=10,
        characters=10_000,
        provider_requests=10,
        estimated_cost=1.0,
        currency="USD",
        price_per_million_characters=100.0,
        pricing_source="test-rate",
        estimated_duration_seconds=120.0,
        estimated_completion_at="2026-08-19T12:02:00+00:00",
        throughput_confidence="high",
        limiting_factor="characters",
        historical_session_count=6,
        quota_remaining=20_000,
        quota_shortfall=0,
        quota_usage_percent=50.0,
        max_queue_cost=2.0,
        budget_usage_percent=50.0,
        risk_level="low",
        reasons=("All checks are within limits.",),
        scenarios=(
            GenerationPlanScenario("base", "Base", 0, 10, 10_000, 10, 1.0, 120.0),
            GenerationPlanScenario("expected", "Expected retries", 20, 10, 12_000, 12, 1.2, 144.0),
            GenerationPlanScenario("stress", "Stress test", 25, 10, 12_500, 12, 1.25, 150.0),
        ),
    )


def _warning_state() -> PreflightState:
    return PreflightState(
        total_jobs=10,
        valid_jobs=10,
        warnings=1,
        estimated_files=10,
        estimated_characters=10_000,
        estimated_provider_requests=10,
        estimated_duration_seconds=120.0,
        estimated_cost=1.0,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="preflight-revision",
        settings_revision="settings-revision",
        generation_plan=_plan(),
        existing_outputs=["one.mp3"],
        issues=[
            PreflightIssue(
                severity="warning",
                row=1,
                filename="one.mp3",
                message="Output file already exists.",
                suggested_action="Review the file policy.",
                code="existing_output",
            )
        ],
    )


def test_b7_unifies_daily_commands_status_and_project_context(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    shell = window.application_shell
    assert shell.root_layout.indexOf(window.metrics_strip) < shell.root_layout.indexOf(window.project_context_widget)
    assert shell.root_layout.indexOf(window.project_context_widget) < shell.root_layout.indexOf(window.main_splitter)
    assert window.metrics_strip.property("workspaceRole") == "daily-command-strip"
    assert window.project_context_widget.strip.parentWidget() is window.project_context_widget.hero
    assert window.project_context_widget.strip.property("embedded") is True
    assert window.project_context_widget.badge_host.isHidden()

    project_button = window.metrics_strip.action_buttons["New Project"]
    assert project_button is window.metrics_strip.action_buttons["Open Project"]
    assert project_button is window.metrics_strip.action_buttons["Save"]
    assert project_button.objectName() == "dailyProjectMenu"
    assert window.metrics_strip.action_buttons["Start Generation"].objectName() == "dailyPrimaryStart"
    assert window.metrics_strip.action_buttons["Add source files"].objectName() == "dailyAddSources"

    assert window.main_toolbar.isHidden()
    assert window.view_toolbar_action.isVisible() is False
    assert window.project_context_widget.browse_csv_button.isHidden()
    assert window.generation_status_strip.start_button.isHidden()
    assert window.generation_status_strip.preflight_button.isHidden()
    assert window.dry_run_button.isHidden()
    window.close()


def test_b7_queue_tools_are_one_open_stacked_accordion_below_rows(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    queue = window.queue_workspace
    accordion = window.queue_tools_accordion
    assert queue.minimal_accordion_active is True
    assert isinstance(accordion, QueueAccordionStack)
    assert queue.body_layout.indexOf(window.table) >= 0
    assert queue.body_layout.indexOf(accordion) > queue.body_layout.indexOf(window.table)
    assert set(accordion.sections) == {"queue-actions", "filters", "batch", "workflow", "columns"}
    assert queue.command_host.isHidden()
    assert window.queue_range_toggle.isHidden()
    assert window.queue_workflow_toggle.isHidden()
    assert window.queue_batch_toggle.isHidden()
    assert all(not accordion.is_expanded(key) for key in accordion.sections)

    accordion.set_expanded("filters", True)
    assert accordion.is_expanded("filters")
    accordion.set_expanded("batch", True)
    assert accordion.is_expanded("batch")
    assert not accordion.is_expanded("filters")
    accordion.set_expanded("workflow", True)
    assert accordion.is_expanded("workflow")
    assert not accordion.is_expanded("batch")
    window.close()


def test_b7_historical_focus_paths_open_the_new_accordion_sections(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    accordion = window.queue_tools_accordion

    window.main_workspace_modernizer.reveal_workflow(True)
    assert accordion.is_expanded("workflow")
    window.main_workspace_modernizer.reveal_batch_planning(True)
    assert accordion.is_expanded("batch")
    assert not accordion.is_expanded("workflow")
    window.main_workspace_modernizer.reveal_range_controls(True)
    assert accordion.is_expanded("batch")
    window.close()


def test_b7_output_is_a_compact_drawer_without_weakening_component_default(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.activity_center.compact_output_mode is True
    assert window.activity_center.compact_output_height == 260
    window.activity_center.show_output_workspace()
    qt_app.processEvents()
    assert window.activity_center.maximumHeight() == 260
    window.close()


def test_b7_preflight_action_is_single_secondary_no_audio_path(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    action = window.actions_by_name["Run Preflight"]
    assert action is window.actions_by_name["Dry run"]
    assert action.text() == "Preflight / dry run"
    assert action in window.metrics_strip.more_menu.actions()
    assert window.dry_run_button.isHidden()
    window.close()


def test_b7_explicit_preflight_synchronizes_visible_scope_and_order_before_reading_jobs() -> None:
    source = inspect.getsource(MainWindow)
    assert "def synchronize_generation_plan_controls" in source
    run_preflight = source.split("def run_preflight", 1)[1].split("def show_preflight_dialog", 1)[0]
    current_state = source.split("def current_preflight_state", 1)[1].split("def run_preflight", 1)[0]
    assert "self.synchronize_generation_plan_controls()" in run_preflight
    assert "self.synchronize_generation_plan_controls()" in current_state
    assert "self.generation_controller.set_scope_mode(self.current_scope_mode())" in source
    assert "self.generation_controller.set_execution_order(self.current_execution_order())" in source


def test_b7_start_makes_explicit_preflight_optional_but_keeps_safety_before_generation() -> None:
    source = inspect.getsource(MainWindow)
    start = source.split("def start(self):", 1)[1].split("def pause", 1)[0]
    current_pos = start.index("state=self.current_preflight_state(s)")
    validate_pos = start.index("state=self.run_preflight(write_report=False)")
    confirm_pos = start.index("generation_confirmation_service.evaluate")
    generate_pos = start.index("self.generation_controller.start(")
    assert current_pos < validate_pos < confirm_pos < generate_pos
    assert "if state is None:" in start
    forbidden = (
        "provider.setCurrent",
        "voice.setText",
        "model.setCurrent",
        "language.setCurrent",
        "apply_smart_provider_routing_recommendation(",
    )
    for token in forbidden:
        assert token not in start




def test_b7_clean_launch_skips_the_second_start_dialog() -> None:
    source = inspect.getsource(MainWindow)
    review = source.split("def review_generation_launch", 1)[1].split(
        "def request_generation_launch_exception", 1
    )[0]
    return_pos = review.index("if not confirmation.requires_user_confirmation: return ()")
    dialog_pos = review.index("GenerationLaunchDialog")
    assert return_pos < dialog_pos


def test_b7_explicit_output_review_has_usable_floor_without_changing_compact_default(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert window.activity_center.compact_output_height == 260
    window.show_output_workspace()
    qt_app.processEvents()

    assert window.activity_center.maximumHeight() >= 300
    assert window.activity_center.maximumHeight() < 400
    window.activity_center.set_expanded(False)
    assert window.activity_center.maximumHeight() == window.activity_center.COLLAPSED_MAX_HEIGHT
    window.close()


def test_b7_reparented_queue_controls_keep_soft_professional_compact_height(
    qt_app, tmp_path: Path
) -> None:
    from app.gui.visual_design_system_v2 import COMPONENTS

    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    window.main_workspace_modernizer.reapply_visual_geometry()
    qt_app.processEvents()

    controls = (
        window.queue_search,
        window.queue_filter,
        window.source_filter,
        window.scope_selector,
        window.order_selector,
        window.use_sort_button,
        window.use_selection_scope_button,
        window.dry_run_button,
        window.retry_menu_button,
        window.clear_completed_button,
    )
    expected_height = COMPONENTS.control_compact_height
    assert {control.minimumHeight() for control in controls} == {expected_height}
    assert {control.maximumHeight() for control in controls} == {expected_height}
    assert {control.height() for control in controls} == {expected_height}
    # Dry Run is intentionally hidden from the B7 daily path; its geometry must
    # still be normalized so historical focus/compatibility paths do not retain
    # the pre-accordion 38px height.
    assert window.dry_run_button.isHidden()
    assert window.dry_run_button.height() == expected_height
    window.close()


def test_b7_accordion_disclosure_does_not_reinflate_legacy_queue_chrome(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    qt_app.processEvents()
    queue = window.queue_workspace
    accordion = window.queue_tools_accordion
    baseline = queue.chrome_host.height()

    window.main_workspace_modernizer.reveal_workflow(True)
    assert accordion.is_expanded("workflow")
    window.main_workspace_modernizer.reveal_batch_planning(True)
    window.main_workspace_modernizer.reapply_visual_geometry()
    qt_app.processEvents()

    assert accordion.is_expanded("batch")
    assert not accordion.is_expanded("workflow")
    assert queue.chrome_host.height() == baseline

    window.main_workspace_modernizer.reveal_batch_planning(False)
    window.main_workspace_modernizer.reapply_visual_geometry()
    qt_app.processEvents()
    assert not accordion.is_expanded("batch")
    assert queue.chrome_host.height() == baseline
    assert queue.chrome_host.height() == queue.chrome_content_height()
    window.close()


def test_b7_h6_keyboard_focus_targets_visible_daily_controls(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert window.focus_workspace_region("queue") is True
    qt_app.processEvents()
    assert window.queue_tools_accordion.is_expanded("filters")
    assert window.queue_search.hasFocus()

    assert window.focus_workspace_region("generation") is True
    qt_app.processEvents()
    assert window.metrics_strip.action_buttons["Start Generation"].hasFocus()
    assert window.dry_run_button.isHidden()
    window.close()


def test_b7_h6_range_host_geometry_tracks_explicit_batch_state(qt_app, tmp_path: Path) -> None:
    from app.gui.visual_design_system_v2 import COMPONENTS

    window = _window(tmp_path)
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(False)
    host = window.queue_workspace.range_host
    assert host.isHidden()
    assert host.minimumHeight() == 0
    assert host.maximumHeight() == 0

    modernizer.reveal_batch_planning(True)
    expected = COMPONENTS.control_compact_height + 8
    assert not host.isHidden()
    assert host.minimumHeight() == expected
    assert host.maximumHeight() == expected

    modernizer.apply_responsive_mode("compact")
    assert host.isHidden()
    assert host.maximumHeight() == 0
    modernizer.apply_responsive_mode("wide")
    assert not host.isHidden()
    assert host.minimumHeight() == expected
    assert host.maximumHeight() == expected
    window.close()


def test_b7_h6_compact_accordion_protects_table_and_legacy_handles(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    queue = window.queue_workspace
    queue.set_compact_mode(True)
    accordion = window.queue_tools_accordion

    assert all(section.header.maximumHeight() <= 24 for section in accordion.sections.values())
    planning_label = queue._command_widgets["planning_label"]
    assert planning_label.isHidden()
    assert planning_label.parentWidget() is queue.command_host
    assert not planning_label.isWindow()

    window.main_workspace_modernizer.apply_responsive_mode("wide")
    assert window.queue_more_actions_button.isHidden()
    assert not window.use_selection_scope_button.isHidden()
    window.main_workspace_modernizer.apply_responsive_mode("standard")
    assert not window.queue_more_actions_button.isHidden()
    assert window.use_selection_scope_button.isHidden()
    window.close()


def test_b7_launch_review_groups_multiple_required_codes_into_one_checkbox(qt_app) -> None:
    state = _warning_state()
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a", skip_existing=True),
    )
    assert len(confirmation.required_acknowledgements) >= 2

    dialog = GenerationLaunchDialog(confirmation, state)
    dialog.show()
    qt_app.processEvents()

    boxes = list(dialog.acknowledgement_boxes.values())
    assert set(dialog.acknowledgement_boxes) == set(confirmation.required_acknowledgements)
    assert len({id(box) for box in boxes}) == 1
    master = boxes[0]
    assert "reviewed the warnings" in master.text().casefold()
    assert dialog.start_button.isEnabled() is False
    master.setChecked(True)
    qt_app.processEvents()
    assert dialog.start_button.isEnabled() is True
    assert set(dialog.acknowledged_codes()) == set(confirmation.required_acknowledgements)
    dialog.close()
