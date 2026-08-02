from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.design_system import (
    WorkspaceDensity,
    density_metrics,
    normalize_density,
    semantic_tone,
)
from app.gui.main import MainWindow
from app.gui.widgets.application_shell import GenerationStatusStrip, ProjectContextBar
from app.services.workspace_profile_service import WorkspaceProfileService


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase23_design_system_normalizes_density_and_status_tones() -> None:
    assert normalize_density("Compact") is WorkspaceDensity.COMPACT
    assert normalize_density("unexpected") is WorkspaceDensity.COMFORTABLE
    assert density_metrics("compact").row_height < density_metrics("comfortable").row_height
    assert semantic_tone("Blocked by errors").value == "error"
    assert semantic_tone("Ready with warnings").value == "warning"
    assert semantic_tone("Generation running").value == "running"
    assert semantic_tone("Completed").value == "success"


def test_phase23_workspace_profiles_include_presentation_rules(tmp_path: Path) -> None:
    service = WorkspaceProfileService(tmp_path / "workspace-profiles.json")

    standard = service.get("Standard")
    compact = service.get("Compact")
    focus = service.get("Focus Mode")

    assert standard.density == "comfortable"
    assert standard.header_mode == "expanded"
    assert compact.density == "compact"
    assert compact.header_mode == "compact"
    assert focus.header_mode == "hidden"
    assert focus.metrics_visible is False


def test_phase23_main_workspace_exposes_professional_shell(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    context = window.project_context_widget
    assert isinstance(context, ProjectContextBar)
    assert context.hero.objectName() == "workspaceHero"
    assert context.project_title.objectName() == "workspaceProjectTitle"
    assert context.provider_badge.objectName() == "workspaceStatusBadge"
    assert context.browse_csv_button.accessibleName() == "Add source files"
    assert window.generation_status_strip.state_badge.objectName() == "generationStateBadge"
    assert window.generation_status_strip.start_button.objectName() == "generationPrimaryAction"
    assert window.actions_by_name["Focus queue"].shortcut().toString() == "Ctrl+Shift+F"
    window.close()


def test_phase23_density_updates_shell_queue_and_persists(qt_app, tmp_path: Path) -> None:
    settings = QSettings("S Talking", "S Talking")
    settings.remove("workspace/density")
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.apply_density("Compact", persist=True)

    assert settings.value("workspace/density") == "compact"
    assert window.density_actions["Compact"].isChecked()
    assert window.queue_workspace.property("density") == "compact"
    assert window.table.verticalHeader().defaultSectionSize() == density_metrics("compact").row_height

    window.apply_density("Comfortable", persist=True)
    assert window.table.verticalHeader().defaultSectionSize() == density_metrics("comfortable").row_height
    window.close()
    settings.remove("workspace/density")


def test_phase23_focus_queue_hides_chrome_and_restores_workspace(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.apply_workspace_preset("Standard", save=False)
    window.toggle_focus_queue(True)
    qt_app.processEvents()

    assert window.focus_queue_action.isChecked()
    assert window.project_context_widget.isVisible() is False
    assert window.metrics_strip.isVisible() is False
    assert window.left_dock.isVisible() is False
    assert window.right_dock.isVisible() is False

    window.toggle_focus_queue(False)
    qt_app.processEvents()
    assert window.layout_actions["Standard"].isChecked()
    assert window.project_context_widget.isVisible() is True
    assert window.metrics_strip.isVisible() is True
    window.close()


def test_phase23_generation_command_dock_reports_state_and_progress(qt_app) -> None:
    strip = GenerationStatusStrip(
        start=lambda: None,
        pause=lambda: None,
        stop=lambda: None,
        show_preflight=lambda: None,
    )
    strip.show()
    qt_app.processEvents()

    strip.set_generation_state("Running", "Six jobs queued")
    strip.set_progress_detail(2, 6, status="completed", filename="lesson-02.mp3")

    assert strip.state_badge.text() == "Completed"
    assert strip.state_badge.property("tone") == "success"
    assert strip.progress_bar.maximum() == 6
    assert strip.progress_bar.value() == 2
    assert "2 of 6" in strip.progress_label.text()
    assert "lesson-02.mp3" in strip.progress_label.text()
    strip.close()


def test_phase23_theme_contains_professional_workspace_contract() -> None:
    source = Path("app/gui/theme.py").read_text(encoding="utf-8")

    for selector in (
        "QFrame#workspaceHero",
        "QLabel#workspaceStatusBadge",
        "QFrame#metricPill",
        "QFrame#generationActionBar",
        "QPushButton#generationPrimaryAction",
    ):
        assert selector in source
