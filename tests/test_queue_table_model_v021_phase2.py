from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy

from app.gui.widgets.queue_table_model import (
    QUEUE_HEADERS,
    QueueColumn,
    QueueDataRole,
    QueueTableModel,
)
from app.models.domain import JobStatus, TTSJob


def _job(row: int, *, text: str = "hej", status: JobStatus = JobStatus.PENDING) -> TTSJob:
    return TTSJob(
        row_number=row,
        source_row=row + 10,
        text=text,
        filename=f"file-{row}.mp3",
        source_display_name="lesson.csv",
        source_sheet="Sheet1",
        status=status,
        retry_count=row % 3,
        duration_seconds=1.25 * row,
    )


def test_queue_table_model_exposes_stable_read_only_snapshot(qt_app) -> None:
    model = QueueTableModel()
    jobs = [_job(1, text="hej verden"), _job(2, text="tak")]
    model.set_jobs(jobs, default_provider="elevenlabs", default_voice="Claus", default_model="eleven_v3")

    assert model.rowCount() == 2
    assert model.columnCount() == len(QUEUE_HEADERS)
    assert model.headerData(QueueColumn.FILENAME, Qt.Horizontal) == "Filename"
    assert model.data(model.index(0, QueueColumn.FILENAME)) == "file-1.mp3"
    assert model.data(model.index(0, QueueColumn.CHARACTERS)) == "10"
    assert model.data(model.index(0, QueueColumn.PROVIDER)) == "elevenlabs"
    assert model.data(model.index(0, QueueColumn.VOICE)) == "Claus"
    assert model.data(model.index(0, QueueColumn.MODEL)) == "eleven_v3"
    assert model.data(model.index(0, 0), QueueDataRole.JOB_ID) == 1
    assert model.job_at(1) is jobs[1]
    assert model.row_for_job_id(2) == 1
    assert model.flags(model.index(0, 0)) == Qt.ItemIsEnabled | Qt.ItemIsSelectable


def test_queue_table_model_has_numeric_sort_roles_and_status_accessibility(qt_app) -> None:
    model = QueueTableModel()
    job = _job(4, text="1234567", status=JobStatus.RUNNING)
    model.set_jobs([job], progress={4: 42.5})

    chars = model.index(0, QueueColumn.CHARACTERS)
    status = model.index(0, QueueColumn.STATUS)
    duration = model.index(0, QueueColumn.DURATION)

    assert model.data(chars, QueueDataRole.SORT_VALUE) == 7
    assert model.data(duration, QueueDataRole.SORT_VALUE) == 5.0
    assert model.data(status, Qt.AccessibleTextRole) == "Status: running"
    assert model.data(status, QueueDataRole.PROGRESS) == 42.5


def test_queue_table_model_updates_one_row_without_model_reset(qt_app) -> None:
    model = QueueTableModel()
    first = _job(1)
    second = _job(2)
    model.set_jobs([first, second])

    reset_spy = QSignalSpy(model.modelReset)
    changed_spy = QSignalSpy(model.dataChanged)
    updated = second.model_copy(update={"status": JobStatus.COMPLETED, "retry_count": 2})

    assert model.update_job(updated, progress=100) is True
    assert model.job_at(1) is updated
    assert model.data(model.index(1, QueueColumn.STATUS)) == "completed"
    assert model.data(model.index(1, QueueColumn.RETRY)) == 2
    assert model.data(model.index(1, QueueColumn.STATUS), QueueDataRole.PROGRESS) == 100
    assert reset_spy.count() == 0
    assert changed_spy.count() == 1


def test_queue_table_model_handles_ten_thousand_jobs_without_item_allocation(qt_app) -> None:
    model = QueueTableModel()
    jobs = [_job(row, text="x" * ((row % 20) + 1)) for row in range(1, 10_001)]

    model.set_jobs(jobs)

    assert model.rowCount() == 10_000
    assert model.row_for_job_id(10_000) == 9_999
    assert model.data(model.index(9_999, QueueColumn.CHARACTERS), QueueDataRole.SORT_VALUE) == 1
    assert model.jobs()[0] is jobs[0]
