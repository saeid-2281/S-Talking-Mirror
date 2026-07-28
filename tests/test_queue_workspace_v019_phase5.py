from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.queue_workspace import QueueScopeSummary


def test_queue_workspace_uses_professional_shared_components(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    assert window.queue_search.objectName() == "queueSearch"
    assert window.queue_search.isClearButtonEnabled()
    assert isinstance(window.queue_scope_summary, QueueScopeSummary)
    assert window.table.objectName() == "queueTable"
    assert window.table.alternatingRowColors() is True
    assert window.table.showGrid() is False
    assert window.table.verticalHeader().defaultSectionSize() == 32
    assert window.table.horizontalHeader().objectName() == "queueHeader"

    window.close()


def test_queue_summary_is_compact_and_scope_aware(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    summary = window.queue_scope_summary
    assert summary.maximumHeight() <= 38
    assert "Visible:" in summary.visible_label.text()
    assert "Selected:" in summary.selected_label.text()
    assert summary.scope_label.text().startswith("Scope:")

    window.close()
