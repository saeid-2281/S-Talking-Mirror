from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_stage3b3_batch_focus_survives_pending_compact_responsive_refresh(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.show()
    window.setGeometry(0, 0, 1366, 768)
    window.apply_workspace_preset("Compact")
    qt_app.processEvents()

    assert not window.queue_tools_accordion.is_expanded("batch")
    assert not window.queue_tools_accordion.is_expanded("workflow")

    # Reproduce the Full Quality Gate timing path deterministically: a pending
    # responsive refresh has no settled prior signature and is ready to fire as
    # soon as control returns to the event loop.
    coordinator = window.responsive_workspace
    coordinator._last_state = None
    coordinator._timer.setInterval(0)
    coordinator.schedule()
    assert coordinator._timer.isActive()

    window.focus_queue_batch_operations()
    qt_app.processEvents()

    assert not coordinator._timer.isActive()
    assert window.queue_tools_accordion.is_expanded("batch")
    assert not window.queue_tools_accordion.is_expanded("workflow")
    window.close()


def test_stage3b3_batch_focus_keeps_historical_disclosure_calls() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def focus_queue_batch_operations", 1)[1].split(
        "def update_queue_scope_summary",
        1,
    )[0]
    assert "responsive_workspace.refresh(force=True)" in method
    assert "main_workspace_modernizer.reveal_batch_planning(True)" in method
    assert "queue_batch_operations.focus_lens()" in method
