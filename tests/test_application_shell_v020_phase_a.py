from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.application_shell import (
    ActivityCenter,
    ApplicationShell,
    GenerationStatusStrip,
    MetricsStrip,
    ProjectContextBar,
)


def test_main_window_uses_independent_application_shell_components(qt_app, tmp_path: Path) -> None:
    window = MainWindow(
        create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    )
    window.show()
    qt_app.processEvents()

    assert isinstance(window.application_shell, ApplicationShell)
    assert window.centralWidget() is window.application_shell
    assert isinstance(window.project_context_widget, ProjectContextBar)
    assert isinstance(window.metrics_strip, MetricsStrip)
    assert isinstance(window.activity_center, ActivityCenter)
    assert isinstance(window.generation_status_strip, GenerationStatusStrip)

    # Compatibility aliases keep existing controllers and tests stable while
    # ownership moves out of MainWindow.
    assert window.project_context_bar is window.project_context_widget.context_label
    assert window.csv is window.project_context_widget.csv
    assert window.out is window.project_context_widget.output
    assert window.cards is window.metrics_strip.cards
    assert window.log is window.activity_center.activity_log
    assert window.startb is window.generation_status_strip.start_button
    assert window.bar is window.generation_status_strip.progress_bar

    window.close()


def test_main_window_no_longer_constructs_shell_regions_inline() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")

    assert "ApplicationShell()" in source
    assert "ProjectContextBar(" in source
    assert "MetricsStrip(" in source
    assert "ActivityCenter()" in source
    assert "GenerationStatusStrip(" in source

    assert "class MetricPill" not in source
    assert "self.activity_tabs=QTabWidget()" not in source
    assert "self.generation_action_bar=QFrame()" not in source
