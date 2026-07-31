from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from app.gui.widgets.queue_table_view import QueueTableView
from app.gui.widgets.queue_view_adapter import QueueViewAdapter
from app.models.domain import JobStatus, TTSJob


def _job(row: int) -> TTSJob:
    return TTSJob(row_number=row, text=f"Text {row}", filename=f"file-{row}.mp3", status=JobStatus.PENDING)


def _legacy_table(jobs: list[TTSJob]) -> QTableWidget:
    table = QTableWidget(len(jobs), 2)
    for row, job in enumerate(jobs):
        item = QTableWidgetItem(str(job.row_number))
        item.setData(Qt.UserRole, job.row_number)
        table.setItem(row, 0, item)
        table.setItem(row, 1, QTableWidgetItem(job.filename))
    return table


def test_adapter_exposes_same_selection_contract_for_legacy_and_model_view(qt_app) -> None:
    jobs = [_job(1), _job(2), _job(3)]
    legacy = _legacy_table(jobs)
    legacy_adapter = QueueViewAdapter(legacy, jobs_provider=lambda: jobs)
    modern = QueueTableView()
    modern.set_jobs(jobs)
    modern_adapter = QueueViewAdapter(modern)

    assert legacy_adapter.is_model_view is False
    assert modern_adapter.is_model_view is True
    assert legacy_adapter.select_job_id(2)
    assert modern_adapter.select_job_id(2)
    assert legacy_adapter.selected_job_ids() == modern_adapter.selected_job_ids() == {2}
    assert [job.row_number for job in legacy_adapter.selected_jobs()] == [2]
    assert [job.row_number for job in modern_adapter.selected_jobs()] == [2]
    assert legacy_adapter.current_job().row_number == modern_adapter.current_job().row_number == 2


def test_adapter_restores_selection_by_identity_after_reorder(qt_app) -> None:
    jobs = [_job(1), _job(2), _job(3)]
    view = QueueTableView()
    adapter = QueueViewAdapter(view)
    adapter.refresh_jobs(jobs)
    adapter.select_job_id(2)

    adapter.refresh_jobs([jobs[2], jobs[0], jobs[1]])

    assert adapter.selected_job_ids() == {2}
    assert adapter.row_for_job_id(2) == 2
    assert adapter.selected_view_rows() == [2]


def test_adapter_can_incrementally_refresh_model_rows(qt_app) -> None:
    jobs = [_job(1), _job(2)]
    view = QueueTableView()
    adapter = QueueViewAdapter(view)
    adapter.refresh_jobs(jobs)
    completed = jobs[1].model_copy(update={"status": JobStatus.COMPLETED})

    assert adapter.refresh_rows([completed]) == 1
    assert adapter.job_at_view_row(1).status is JobStatus.COMPLETED
    assert adapter.refresh_rows([_job(999)]) == 0


def test_adapter_requires_job_provider_for_legacy_table(qt_app) -> None:
    table = QTableWidget(0, 2)
    try:
        QueueViewAdapter(table)
    except TypeError as error:
        assert "jobs_provider" in str(error)
    else:
        raise AssertionError("Expected legacy adapter construction to require jobs_provider")


def test_adapter_maps_context_menu_position_through_viewport(qt_app) -> None:
    jobs = [_job(1)]
    table = _legacy_table(jobs)
    adapter = QueueViewAdapter(table, jobs_provider=lambda: jobs)
    point = QPoint(5, 7)

    assert adapter.map_viewport_to_global(point) == table.viewport().mapToGlobal(point)
