from __future__ import annotations

import ast
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.generation_journey import GenerationJourneyWidget
from app.models.generation_journey import build_generation_journey_state


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/gui/main.py"
MODEL = ROOT / "app/models/generation_journey.py"
WIDGET = ROOT / "app/gui/widgets/generation_journey.py"
DOC = ROOT / "docs/GENERATION_UX_2_PHASE89.md"


def _state(**updates):
    values = {
        "total_jobs": 10,
        "total_characters": 5000,
        "scoped_jobs": 10,
        "scoped_characters": 5000,
        "provider_display": "Mock",
        "provider_state": "Ready",
        "provider_detail": "Local provider ready.",
        "model_label": "mock-v1",
        "voice_label": "Provider default",
        "voice_required": False,
        "scope_label": "Entire queue",
        "preflight_status": "Ready",
        "preflight_errors": 0,
        "preflight_warnings": 0,
        "generation_active": False,
    }
    values.update(updates)
    return build_generation_journey_state(**values)


def test_phase89_empty_queue_routes_to_source_preparation() -> None:
    state = _state(total_jobs=0, total_characters=0, scoped_jobs=0, scoped_characters=0)
    assert state.headline == "Prepare your source"
    assert state.next_action_code == "prepare-source"
    assert state.next_action_label == "Prepare text"
    assert state.steps[0].complete is False


def test_phase89_provider_setup_is_next_after_source() -> None:
    state = _state(
        provider_state="Setup required",
        provider_detail="API key is required.",
    )
    assert state.next_action_code == "provider"
    assert state.steps[1].status == "Review"
    assert "API key" in state.summary


def test_phase89_voice_gap_is_visible_without_bypassing_provider() -> None:
    state = _state(voice_label="", voice_required=True)
    assert state.next_action_code == "voice"
    assert state.next_action_label == "Choose voice"
    assert state.steps[2].complete is False


def test_phase89_empty_scope_routes_to_scope_selector() -> None:
    state = _state(scoped_jobs=0, scoped_characters=0, scope_label="Selected rows")
    assert state.next_action_code == "scope"
    assert state.steps[3].status == "Empty"
    assert "selected rows" in state.summary.lower()


def test_phase89_preflight_is_authoritative_before_start() -> None:
    unchecked = _state(preflight_status="Not checked")
    blocked = _state(
        preflight_status="Blocked by errors",
        preflight_errors=2,
        preflight_warnings=1,
    )
    assert unchecked.next_action_code == "preflight"
    assert unchecked.ready_to_start is False
    assert blocked.next_action_code == "preflight"
    assert blocked.next_action_label == "Review preflight"
    assert blocked.steps[4].tone == "error"


def test_phase89_ready_with_warnings_can_reach_guarded_start() -> None:
    state = _state(preflight_status="Ready with warnings", preflight_warnings=2)
    assert state.ready_to_start is True
    assert state.next_action_code == "start"
    assert state.next_action_label == "Review & start"
    assert state.steps[4].tone == "warning"


def test_phase89_active_generation_disables_smart_cta() -> None:
    state = _state(generation_active=True)
    assert state.generation_active is True
    assert state.next_action_code == ""
    assert state.next_action_label == "Generation running"


def test_phase89_widget_renders_steps_and_emits_existing_action_codes(qt_app) -> None:
    widget = GenerationJourneyWidget()
    state = _state(preflight_status="Not checked")
    widget.set_state(state)

    assert widget.headline.text() == "Validate the batch"
    assert widget.primary_action.text() == "Run preflight"
    assert len(widget.step_buttons) == 5
    assert "Ready" in widget.step_buttons["source"].text()

    requested: list[str] = []
    widget.actionRequested.connect(requested.append)
    widget.step_buttons["voice"].click()
    widget.primary_action.click()

    assert requested == ["voice", "preflight"]
    widget.close()


def test_phase89_compact_mode_yields_vertical_space_to_queue(qt_app) -> None:
    widget = GenerationJourneyWidget()
    widget.set_state(_state())
    widget.show()
    qt_app.processEvents()

    widget.set_compact_mode(True)
    qt_app.processEvents()

    assert widget.isHidden()
    assert widget.steps_host.isHidden()
    assert widget.summary.isHidden()
    assert not widget.primary_action.isHidden()
    # The process-global Qt stylesheet can raise minimumHeight() on this
    # standalone hidden widget depending on earlier full-suite theme tests.
    # That value is not the queue-space authority: A9/H4 detach the disclosure
    # structurally while collapsed.  Keep the explicit compact cap and visible
    # child contract without making this test order-dependent on global QSS.
    assert widget.maximumHeight() == 52

    widget.set_compact_mode(False)
    qt_app.processEvents()
    assert not widget.isHidden()
    assert widget.maximumHeight() == 104
    widget.close()


def test_phase89_main_integrates_journey_without_new_launch_path() -> None:
    source = MAIN.read_text(encoding="utf-8")
    ast.parse(source)

    assert "GenerationJourneyWidget" in source
    assert "build_generation_journey_state" in source
    assert "def refresh_generation_journey(self):" in source
    assert "def handle_generation_journey_action(self,code):" in source
    assert "Ctrl+Alt+G" in source
    assert "Generation: Focus workflow" in source
    assert "'start':self.start" in source
    assert "'preflight':self.dry_run" in source
    assert "self.context.provider_readiness_service.readiness_for(" in source



def test_phase89_mainwindow_hosts_live_journey(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))

    # B7 keeps the historical journey instance and shortcut while moving its
    # presentation into the Workflow accordion below the queue rows.
    assert window.queue_workspace.root_layout.indexOf(window.generation_journey) == -1
    assert not window.queue_tools_accordion.is_expanded("workflow")
    assert window.actions_by_name["Generation Workflow"].shortcut().toString() == "Ctrl+Alt+G"
    assert window.generation_journey.state is not None
    assert window.generation_journey.state.next_action_code == "prepare-source"

    window.focus_generation_workflow()
    qt_app.processEvents()
    assert window.queue_workspace.root_layout.indexOf(window.generation_journey) == -1
    assert window.queue_tools_accordion.is_expanded("workflow")
    window.close()


def test_phase89_compact_workspace_hides_journey_for_queue_dominance(
    qt_app, tmp_path: Path
) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    window.setGeometry(0, 0, 1366, 768)
    window.apply_workspace_preset("Compact")
    qt_app.processEvents()

    assert not window.queue_tools_accordion.is_expanded("workflow")
    assert window.queue_workspace.property("compact") is True

    window.focus_generation_workflow()
    qt_app.processEvents()
    assert window.queue_tools_accordion.is_expanded("workflow")
    window.close()


def test_phase89_source_and_documentation_contracts() -> None:
    ast.parse(MODEL.read_text(encoding="utf-8"))
    ast.parse(WIDGET.read_text(encoding="utf-8"))
    documentation = DOC.read_text(encoding="utf-8")
    for phrase in (
        "S-Talking 1.1 product-value track",
        "does **not bypass",
        "`MainWindow.start()` remains the only launch path",
        "ProviderReadinessService",
        "Ctrl+Alt+G",
        "does not change queue ordering",
    ):
        assert phrase in documentation
