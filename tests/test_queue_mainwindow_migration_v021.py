from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QTableWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.queue_table_view import QueueTableView
from app.models.domain import JobStatus, TTSJob


def _job(row: int) -> TTSJob:
    return TTSJob(
        row_number=row,
        text=f"Text {row}",
        filename=f"file-{row}.mp3",
        status=JobStatus.PENDING,
    )


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))


def test_queue_model_view_feature_flag_activates_real_mainwindow_view(qt_app, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S_TALKING_QUEUE_MODEL_VIEW", "1")
    window = _window(tmp_path)
    jobs = [_job(1), _job(2), _job(3)]
    window.generation_controller.set_jobs(jobs)

    window.render_queue()
    qt_app.processEvents()

    assert window.queue_model_view_active is True
    assert isinstance(window.table, QueueTableView)
    assert window.queue_adapter.is_model_view is True
    assert window.table.model().rowCount() == 3
    assert window.queue_adapter.job_ids() == (1, 2, 3)
    assert window.queue_adapter.select_job_id(2)
    assert window.selected_queue_jobs() == [jobs[1]]
    window.close()


def test_queue_model_view_feature_flag_can_force_legacy_fallback(qt_app, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S_TALKING_QUEUE_MODEL_VIEW", "0")
    window = _window(tmp_path)

    assert window.queue_model_view_active is False
    assert isinstance(window.table, QTableWidget)
    assert window.queue_adapter.is_model_view is False
    window.close()


def test_model_view_queue_clears_without_qtablewidget_api(qt_app, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S_TALKING_QUEUE_MODEL_VIEW", "true")
    window = _window(tmp_path)
    window.generation_controller.set_jobs([_job(1), _job(2)])
    window.render_queue()
    assert window.table.model().rowCount() == 2

    window.clear_queue_view()

    assert window.table.model().rowCount() == 0
    window.close()


def test_mainwindow_queue_interactions_are_adapter_backed() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")

    assert "self.queue_adapter=QueueViewAdapter" in source
    assert "self.queue_adapter.selected_jobs()" in source
    assert "self.queue_adapter.map_viewport_to_global(pos)" in source
    assert "S_TALKING_QUEUE_MODEL_VIEW" in source
