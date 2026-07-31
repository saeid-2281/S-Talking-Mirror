from __future__ import annotations

from app.gui.widgets.queue_table_view import QueueTableView
from app.models.domain import JobStatus, TTSJob


def _job(row: int, filename: str) -> TTSJob:
    return TTSJob(row_number=row, text=f"Text {row}", filename=filename, status=JobStatus.PENDING)


def test_queue_table_view_uses_queue_model(qt_app) -> None:
    view = QueueTableView()
    jobs = [_job(1, "a.mp3"), _job(2, "b.mp3")]

    view.set_jobs(jobs)

    assert view.model() is view.queue_model
    assert view.queue_model.rowCount() == 2
    assert view.job_at_view_row(1) is jobs[1]


def test_queue_table_view_preserves_selection_by_job_id(qt_app) -> None:
    view = QueueTableView()
    first = [_job(1, "a.mp3"), _job(2, "b.mp3"), _job(3, "c.mp3")]
    view.set_jobs(first)
    assert view.select_job_id(2)
    assert view.selected_job_ids() == {2}

    reordered = [first[2], first[1], first[0]]
    view.set_jobs(reordered)

    assert view.selected_job_ids() == {2}
    assert [job.row_number for job in view.selected_jobs()] == [2]


def test_queue_table_view_can_select_and_scroll_by_identity(qt_app) -> None:
    view = QueueTableView()
    view.set_jobs([_job(i, f"{i}.mp3") for i in range(1, 101)])

    assert view.select_job_id(75)
    assert view.currentIndex().row() == 74
    assert view.selected_job_ids() == {75}
    assert view.select_job_id(999) is False
