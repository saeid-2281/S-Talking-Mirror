from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.gui.dialogs.project_session_workflow_dialog import ProjectSessionWorkflowDialog
from app.models import AppSettings, JobStatus, TTSJob
from app.models.product_events import BatchSessionRecord
from app.models.project_session_workflow import ProjectContinuationSummary, SessionContinuationSummary
from app.repositories import JobRepository, ProjectRepository
from app.repositories.product_event_repository import ProductEventRepository
from app.services.project_session_workflow_service import ProjectSessionWorkflowService
from app.services.startup_recovery_service import SessionRestoreService


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "gui" / "main.py"
SERVICE = ROOT / "app" / "services" / "project_session_workflow_service.py"
DOC = ROOT / "docs" / "PROJECT_SESSION_WORKFLOW_PHASE95.md"


def _workflow(tmp_path: Path):
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    database = Database(runtime.database_path)
    database.initialize()
    projects = ProjectRepository(database)
    jobs = JobRepository(database)
    events = ProductEventRepository(database)
    session = SessionRestoreService(runtime)
    service = ProjectSessionWorkflowService(database, projects, events, session)
    return runtime, database, projects, jobs, events, session, service


def _project(tmp_path: Path, projects: ProjectRepository, name: str = "Demo"):
    project_file = tmp_path / f"{name}.stproj"
    project_file.write_text("{}", encoding="utf-8")
    source = tmp_path / f"{name}.csv"
    source.write_text("text,filename\nhello,hello\n", encoding="utf-8")
    output = tmp_path / f"{name}-out"
    output.mkdir()
    record = projects.create(
        name=name,
        provider="mock",
        settings=AppSettings(provider="mock"),
        project_file=str(project_file),
        csv_path=str(source),
        output_path=str(output),
    )
    projects.touch_last_opened(record.id)
    return projects.get_by_id(record.id), project_file, source, output


def test_phase95_summary_preserves_explicit_continuation_contract() -> None:
    session = SessionContinuationSummary(True, "demo.stproj", "Demo", 1, True, "failed", 4)
    project = ProjectContinuationSummary(1, "Demo", "demo.stproj", None, None, "mock", "now", True, False, False, 4, 2, 1, 1, 0)
    assert session.can_continue is True
    assert project.can_continue is True
    assert "4 jobs" in project.queue_summary
    assert "1 failed" in project.queue_summary


def test_phase95_service_aggregates_saved_queue_without_mutation(tmp_path: Path) -> None:
    _runtime, database, projects, jobs, _events, _session, service = _workflow(tmp_path)
    record, _project_file, _source, output = _project(tmp_path, projects)
    assert record is not None
    items = [
        TTSJob(row_number=1, text="one", filename="one", status=JobStatus.PENDING),
        TTSJob(row_number=2, text="two", filename="two", status=JobStatus.FAILED, error="x"),
        TTSJob(row_number=3, text="three", filename="three", status=JobStatus.COMPLETED),
    ]
    jobs.upsert_jobs(record.id, items, output_dir=output, extension=".wav")
    with database.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    summary = service.project_summary(record.id)
    with database.connect() as connection:
        after = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert summary is not None
    assert (summary.saved_jobs, summary.pending_jobs, summary.failed_jobs, summary.completed_jobs) == (3, 1, 1, 1)
    assert before == after == 3


def test_phase95_service_surfaces_existing_latest_audio_only(tmp_path: Path) -> None:
    _runtime, _database, projects, jobs, _events, _session, service = _workflow(tmp_path)
    record, _project_file, _source, output = _project(tmp_path, projects)
    assert record is not None
    audio = output / "ready.wav"
    audio.write_bytes(b"RIFFphase95")
    item = TTSJob(row_number=1, text="ready", filename="ready", status=JobStatus.COMPLETED)
    jobs.upsert_jobs(record.id, [item], output_dir=output, extension=".wav")
    summary = service.project_summary(record.id)
    assert summary is not None
    assert summary.latest_audio_path == str(audio)
    audio.unlink()
    assert service.project_summary(record.id).latest_audio_path is None


def test_phase95_recent_run_summary_uses_existing_batch_history(tmp_path: Path) -> None:
    _runtime, _database, projects, _jobs, events, _session, service = _workflow(tmp_path)
    record, _project_file, _source, output = _project(tmp_path, projects)
    assert record is not None
    report = tmp_path / "report.html"
    report.write_text("ok", encoding="utf-8")
    events.add_batch_session(BatchSessionRecord(
        session_id="run-95", project_id=record.id, scope="entire_queue", provider="mock",
        model="m", voice="v", total_jobs=5, completed_jobs=4, failed_jobs=1,
        skipped_jobs=0, character_count=100, report_path=str(report), output_path=str(output),
        result="partial", started_at="2026-08-09T19:00:00+00:00", finished_at="2026-08-09T19:01:00+00:00",
        elapsed_seconds=60.0,
    ))
    snapshot = service.snapshot()
    assert snapshot.projects[0].latest_run is not None
    assert snapshot.projects[0].latest_run.session_id == "run-95"
    runs = service.recent_runs(record.id)
    assert len(runs) == 1 and runs[0].failed_jobs == 1


def test_phase95_session_summary_reuses_session_restore_state(tmp_path: Path) -> None:
    _runtime, _database, projects, _jobs, _events, session, service = _workflow(tmp_path)
    record, project_file, _source, _output = _project(tmp_path, projects)
    assert record is not None
    session.save(last_project_path=project_file, queue_filter="failed", selected_row=7)
    summary = service.session_summary()
    assert summary.can_continue is True
    assert summary.project_id == record.id
    assert summary.queue_filter == "failed"
    assert summary.selected_row == 7


def test_phase95_missing_last_session_is_not_continuable(tmp_path: Path) -> None:
    _runtime, _database, _projects, _jobs, _events, session, service = _workflow(tmp_path)
    missing = tmp_path / "missing.stproj"
    session.save(last_project_path=missing, queue_filter="all", selected_row=None)
    summary = service.session_summary()
    assert summary.project_path == str(missing)
    assert summary.can_continue is False


def test_phase95_dialog_exposes_explicit_continue_and_read_only_run_actions(qt_app, tmp_path: Path) -> None:
    _runtime, _database, projects, _jobs, events, session, service = _workflow(tmp_path)
    record, project_file, _source, output = _project(tmp_path, projects)
    assert record is not None
    session.save(last_project_path=project_file, queue_filter="all", selected_row=0)
    report = tmp_path / "report.html"
    report.write_text("ok", encoding="utf-8")
    events.add_batch_session(BatchSessionRecord(
        session_id="run-dialog", project_id=record.id, scope="entire_queue", provider="mock", model="m", voice="v",
        total_jobs=1, completed_jobs=1, failed_jobs=0, skipped_jobs=0, character_count=4,
        report_path=str(report), output_path=str(output), result="completed", started_at="2026-08-09T19:00:00+00:00",
        finished_at="2026-08-09T19:00:10+00:00", elapsed_seconds=10,
    ))
    dialog = ProjectSessionWorkflowDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.continue_session_button.isEnabled()
    assert dialog.continue_project_button.isEnabled()
    assert dialog.open_run_output_button.isEnabled()
    assert dialog.open_report_button.isEnabled()


def test_phase95_dialog_continue_project_returns_path_without_starting_work(qt_app, tmp_path: Path) -> None:
    _runtime, _database, projects, _jobs, _events, _session, service = _workflow(tmp_path)
    _record, project_file, _source, _output = _project(tmp_path, projects)
    dialog = ProjectSessionWorkflowDialog(service)
    dialog.show()
    qt_app.processEvents()
    dialog.continue_project()
    assert dialog.result() == QDialog.Accepted
    assert dialog.action == ProjectSessionWorkflowDialog.CONTINUE_PROJECT
    assert dialog.selected_path == str(project_file)


def test_phase95_dialog_continue_session_returns_existing_restore_path(qt_app, tmp_path: Path) -> None:
    _runtime, _database, projects, _jobs, _events, session, service = _workflow(tmp_path)
    _record, project_file, _source, _output = _project(tmp_path, projects)
    session.save(last_project_path=project_file, queue_filter="pending", selected_row=2)
    dialog = ProjectSessionWorkflowDialog(service)
    dialog.show()
    qt_app.processEvents()
    dialog.continue_session()
    assert dialog.action == ProjectSessionWorkflowDialog.CONTINUE_SESSION
    assert dialog.selected_path == str(project_file)


def test_phase95_container_and_application_context_expose_one_shared_service(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    container = create_service_container(runtime)
    context = create_application_context(container)
    assert context.project_session_workflow_service is container.project_session_workflow_service
    assert context.project_session_workflow_service.session_restore is container.session_restore_service


def test_phase95_main_exposes_shortcut_palette_and_existing_open_restore_route() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert "Project Continuity" in source
    assert "Ctrl+Alt+P" in source
    assert "Project: Continue Work" in source
    method = source.split("    def _continue_project_path", 1)[1].split("    def open_project_continuity", 1)[0]
    assert "self.project_controller.open_project" in method
    assert "self.restore_project_queue()" in method
    assert "self.load_csv(update_project=False)" in method
    assert "self.start(" not in method
    assert "retry_" not in method


def test_phase95_service_is_read_only_and_adds_no_session_store() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    upper = source.upper()
    assert "INSERT " not in upper
    assert "UPDATE " not in upper
    assert "DELETE " not in upper
    assert "SESSIONRESTORESERVICE" in upper
    assert "BATCH_SESSIONS" not in source  # history is accessed through ProductEventRepository


def test_phase95_documentation_preserves_safe_resume_authority() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "does **not** add a database migration" in source
    assert "Generation Safe Resume remains the only run-resume workflow" in source
    assert "never starts generation" in source
