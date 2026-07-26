from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, JobStatus, TTSJob
from app.services.queue_service import QueueService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=2, filename="one.wav", text="one"),
        TTSJob(row_number=3, filename="two.wav", text="two", status=JobStatus.FAILED, error="boom"),
        TTSJob(row_number=4, filename="three.wav", text="three", status=JobStatus.COMPLETED),
    ]


def test_status_filtering_does_not_modify_underlying_jobs() -> None:
    service = QueueService()
    queue = jobs()

    failed = service.visible_jobs(queue, "failed")

    assert [job.filename for job in failed] == ["two.wav"]
    assert len(queue) == 3


def test_retry_failed_retry_selected_skip_and_reset_selected() -> None:
    service = QueueService()
    queue = jobs()

    assert service.retry_failed(None, queue) == 1
    assert queue[1].status == JobStatus.PENDING
    queue[1].status = JobStatus.FAILED
    assert service.retry_selected(None, queue, [queue[1]]) == 1
    assert queue[1].status == JobStatus.PENDING
    assert service.skip_selected(None, queue, [queue[0]]) == 1
    assert queue[0].status == JobStatus.SKIPPED
    assert service.reset_jobs(None, queue, [queue[0]]) == 1
    assert queue[0].status == JobStatus.PENDING


def test_clear_completed_removes_only_visible_completed_jobs() -> None:
    service = QueueService()
    queue = jobs()

    assert service.clear_completed(None, queue, status_filter="failed") == 0
    assert len(queue) == 3
    assert service.clear_completed(None, queue, status_filter="all") == 1
    assert [job.filename for job in queue] == ["one.wav", "two.wav"]


def test_interrupted_job_recovery_and_missing_output_reset(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    project = container.project_controller.new_project("Queue", None, tmp_path / "out", AppSettings(provider="mock"))
    output = tmp_path / "out" / "done.wav"
    output.parent.mkdir()
    output.write_bytes(b"RIFFdata")
    queue = [
        TTSJob(row_number=2, filename="run.wav", text="run", status=JobStatus.RUNNING),
        TTSJob(row_number=3, filename="done.wav", text="done", status=JobStatus.COMPLETED),
        TTSJob(row_number=4, filename="missing.wav", text="missing", status=JobStatus.COMPLETED),
    ]
    container.job_repository.upsert_jobs(project.project_id, queue, output_dir=tmp_path / "out", extension=".wav")
    container.job_repository.mark_running(project.project_id, queue[0])
    container.job_repository.mark_result(project.project_id, queue[1], JobStatus.COMPLETED, output_path=output)
    container.job_repository.mark_result(
        project.project_id,
        queue[2],
        JobStatus.COMPLETED,
        output_path=tmp_path / "out" / "missing.wav",
    )

    restored = container.job_repository.restore_jobs(project.project_id, output_dir=tmp_path / "out")

    assert [job.status for job in restored] == [JobStatus.PENDING, JobStatus.COMPLETED, JobStatus.PENDING]


def test_queue_persistence_and_restoration(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    project = container.project_controller.new_project("Queue", None, tmp_path / "out", AppSettings(provider="mock"))
    queue = [TTSJob(row_number=2, filename="one.wav", text="one")]

    container.generation_controller.set_jobs(
        queue,
        project_id=project.project_id,
        output_dir=tmp_path / "out",
        settings=AppSettings(provider="mock"),
    )
    container.job_repository.mark_result(project.project_id, queue[0], JobStatus.FAILED, error="boom")

    restored = create_service_container(RuntimeConfig.from_root(tmp_path)).job_repository.restore_jobs(project.project_id)

    assert restored[0].status == JobStatus.FAILED
    assert restored[0].error == "boom"


def test_pending_only_generation_and_skip_existing(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    project = container.project_controller.new_project("Queue", None, tmp_path / "out", AppSettings(provider="mock"))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "done.wav").write_bytes(b"done")
    (output_dir / "skip.wav").write_bytes(b"existing")
    queue = [
        TTSJob(row_number=2, filename="done.wav", text="done", status=JobStatus.COMPLETED),
        TTSJob(row_number=3, filename="make.wav", text="make"),
        TTSJob(row_number=4, filename="skip.wav", text="skip"),
    ]
    container.generation_controller.set_jobs(
        queue,
        project_id=project.project_id,
        output_dir=output_dir,
        settings=AppSettings(provider="mock"),
    )

    assert container.generation_controller.start(qt_app, AppSettings(provider="mock", delay_seconds=0), output_dir, project.project_key)
    wait_until_inactive(qt_app, container.generation_controller)

    statuses = [job.status for job in container.generation_controller.jobs]
    assert statuses == [JobStatus.COMPLETED, JobStatus.COMPLETED, JobStatus.SKIPPED]
    assert container.generation_controller.metrics().failed == 0


def test_stop_leaves_remaining_jobs_pending(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    project = container.project_controller.new_project("Queue", None, tmp_path / "out", AppSettings(provider="mock"))
    queue = [TTSJob(row_number=index, filename=f"{index}.wav", text="make") for index in range(2, 8)]
    container.generation_controller.set_jobs(
        queue,
        project_id=project.project_id,
        output_dir=tmp_path / "out",
        settings=AppSettings(provider="mock"),
    )

    assert container.generation_controller.start(
        qt_app,
        AppSettings(provider="mock", delay_seconds=0.05),
        tmp_path / "out",
        project.project_key,
    )
    time.sleep(0.02)
    container.generation_controller.stop()
    wait_until_inactive(qt_app, container.generation_controller)

    assert any(job.status == JobStatus.PENDING for job in container.generation_controller.jobs)
    assert all(job.status != JobStatus.FAILED for job in container.generation_controller.jobs)


def test_eta_uses_historical_average_and_counts_pending_running(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    project = container.project_controller.new_project("Queue", None, tmp_path / "out", AppSettings(provider="mock"))
    queue = [
        TTSJob(row_number=2, filename="done.wav", text="done", status=JobStatus.COMPLETED),
        TTSJob(row_number=3, filename="run.wav", text="run", status=JobStatus.RUNNING),
        TTSJob(row_number=4, filename="pending.wav", text="pending"),
    ]
    container.job_repository.upsert_jobs(project.project_id, queue, output_dir=tmp_path / "out", extension=".wav")
    container.job_repository.mark_result(project.project_id, queue[0], JobStatus.COMPLETED, duration_seconds=5.0)
    service = QueueService(container.job_repository)

    metrics = service.metrics(queue, project_id=project.project_id)

    assert metrics.eta_seconds == 10.0


def test_gui_queue_actions_and_context_menu_exist(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(_context(tmp_path))
    texts = [
        window.queue_filter.itemText(index)
        for index in range(window.queue_filter.count())
    ]

    assert texts == ["All", "Pending", "Running", "Completed", "Failed", "Skipped"]
    assert window.retry_failed_button.text() == "Retry Failed"
    assert window.retry_selected_button.text() == "Retry Selected"
    assert window.skip_selected_button.text() == "Skip Selected"
    assert window.reset_selected_button.text() == "Reset Selected"
    assert window.clear_completed_button.text() == "Clear Completed"
    assert window.open_output_button.text() == "Open Output"
    assert window.table.contextMenuPolicy() == Qt.CustomContextMenu


def _context(tmp_path: Path):
    from app.bootstrap import create_application_context

    return create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))


def wait_until_inactive(qt_app, controller) -> None:
    deadline = time.time() + 5
    while controller.is_active and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    qt_app.processEvents()
