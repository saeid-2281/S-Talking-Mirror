from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, JobStatus, ProjectState, TTSJob
from app.services.report_service import ReportService
from app.services.statistics_service import StatisticsService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_dashboard_values_before_during_and_after_generation(tmp_path: Path) -> None:
    jobs = [
        TTSJob(row_number=1, filename="one.wav", text="hello"),
        TTSJob(row_number=2, filename="two.wav", text="world!"),
    ]
    service = StatisticsService(tmp_path / "state.db", fallback_seconds_per_job=4.0)

    before = service.dashboard_for_jobs(jobs)
    assert before.total_files == 2
    assert before.total_characters == 11
    assert before.pending == 2
    assert before.estimated_seconds == 8.0

    jobs[0].status = JobStatus.COMPLETED
    during = service.dashboard_for_jobs(jobs)
    assert during.completed == 1
    assert during.pending == 1
    assert during.estimated_seconds == 4.0

    jobs[1].status = JobStatus.FAILED
    after = service.dashboard_for_jobs(jobs)
    assert after.completed == 1
    assert after.failed == 1
    assert after.pending == 0
    assert after.estimated_seconds == 0.0


def test_report_service_writes_all_files_and_redacts_secrets(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = ReportService(runtime)
    project = ProjectState(1, "Danish", None, None, tmp_path / "out", "elevenlabs")
    settings = AppSettings(provider="elevenlabs", api_key="sk_SECRET", voice_id="voice", model_id="model")
    jobs = [TTSJob(row_number=1, filename="one", text="hello", status=JobStatus.FAILED, error="Bearer SECRET")]

    report = service.create_generation_report(
        project=project,
        settings=settings,
        jobs=jobs,
        output_dir=tmp_path / "out",
        summary={"total": 1, "completed": 0, "failed": 1, "skipped": 0},
        started_at=datetime.now(timezone.utc),
        log_events=["request sk_SECRET failed"],
    )

    expected = [
        "summary.json",
        "summary.md",
        "report.html",
        "generation.log",
        "jobs.csv",
        "failed.csv",
        "skipped.csv",
        "diagnostics.json",
    ]
    for name in expected:
        assert (report.report_dir / name).exists()
    assert json.loads((report.report_dir / "summary.json").read_text(encoding="utf-8"))["failed"] == 1
    assert "Failed Jobs" in (report.report_dir / "summary.md").read_text(encoding="utf-8")
    assert "<html" in (report.report_dir / "report.html").read_text(encoding="utf-8")

    bundle = service.export_diagnostics_bundle(report.report_dir)
    assert bundle.exists()
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert "diagnostics/latest_report/summary.json" in names
        content = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if not name.endswith("/")
        )
    all_report_text = "\n".join(path.read_text(encoding="utf-8") for path in report.report_dir.iterdir())
    assert "sk_SECRET" not in all_report_text
    assert "Bearer SECRET" not in all_report_text
    assert "sk_SECRET" not in content
    assert "Bearer SECRET" not in content


def test_offscreen_app_smoke_creates_dashboard_and_report(qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    context.notification_service = FakeNotifications()
    window = MainWindow(context)
    window.provider.setCurrentText("mock")
    window.delay.setValue(0)
    window.key.setText("sk_SECRET")
    csv_path = Path("sample/input.csv").resolve()
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    state = window.project_controller.new_project("Smoke", csv_path, output_dir, window.settings())
    window.apply_project_state(state)
    window.load_csv(update_project=False)

    assert window.cards["files"].value.text() != "0"
    assert window.cards["chars"].value.text() != "0"

    window.start()
    deadline = time.time() + 10
    while window.generation_controller.is_active and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    qt_app.processEvents()

    assert window.generation_controller.is_active is False
    assert window.cards["done"].value.text() != "0"
    report_dir = context.report_service.latest_report_dir()
    assert report_dir is not None
    assert (report_dir / "summary.json").exists()
    report_text = "\n".join(path.read_text(encoding="utf-8") for path in report_dir.iterdir())
    assert "sk_SECRET" not in report_text
    assert not window.report_dialogs
    assert not window.report_button.isHidden()
    assert "Report" in window.report_button.text()
    window.close()
    qt_app.processEvents()


class FakeNotifications:
    parent: object | None = None

    def information(self, title: str, message: str) -> None:
        pass

    def warning(self, title: str, message: str) -> None:
        pass

    def error(self, title: str, message: str) -> None:
        pass

    def confirmation(self, title: str, message: str) -> bool:
        return True

    def show_generation_summary(self, summary: dict) -> None:
        pass
