"""Stage 3B-2: one stable queue hydration when no output reset is necessary."""
from __future__ import annotations

import ast
from pathlib import Path

from app.database.connection import Database
from app.models.domain import JobStatus, TTSJob
from app.repositories.job_repository import JobRepository


class CountingRepository(JobRepository):
    def __init__(self, database):
        super().__init__(database)
        self.full_reads = 0

    def list_by_project(self, project_id):
        self.full_reads += 1
        return super().list_by_project(project_id)


def repository(tmp_path):
    database = Database(tmp_path / "queue.sqlite")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO projects(name, csv_path, output_path, provider, settings_json, created_at, updated_at) "
            "VALUES('test', NULL, NULL, 'mock', '{}', '2026-01-01', '2026-01-01')"
        )
        project_id = connection.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]
    return CountingRepository(database), project_id


def test_pending_large_project_single_full_read(tmp_path):
    repo, project_id = repository(tmp_path)
    rows = [TTSJob(row_number=index, filename=f"file_{index}", text=f"text {index}") for index in range(1, 2001)]
    repo.upsert_jobs(project_id, rows, output_dir=tmp_path / "out")
    restored = repo.restore_jobs(project_id, output_dir=tmp_path / "out")
    assert repo.full_reads == 1
    assert len(restored) == 2000
    assert [job.row_number for job in restored] == list(range(1, 2001))
    assert all(job.status == JobStatus.PENDING for job in restored)


def test_intact_completed_output_single_full_read_preserves_metadata(tmp_path):
    repo, project_id = repository(tmp_path)
    audio = tmp_path / "good.wav"
    audio.write_bytes(b"real output")
    row = TTSJob(row_number=5, filename="five", text="hello", status=JobStatus.COMPLETED,
                 retry_count=3, duration_seconds=4.5, generated_output_path=str(audio))
    repo.upsert_jobs(project_id, [row])
    restored = repo.restore_jobs(project_id, output_dir=tmp_path)
    assert repo.full_reads == 1
    assert len(restored) == 1
    assert restored[0].status == JobStatus.COMPLETED
    assert restored[0].retry_count == 3
    assert restored[0].duration_seconds == 4.5
    assert restored[0].generated_output_path == str(audio)
    assert audio.read_bytes() == b"real output"


def test_missing_completed_output_resets_database_before_return(tmp_path):
    repo, project_id = repository(tmp_path)
    missing = tmp_path / "gone.wav"
    row = TTSJob(row_number=1, filename="gone", text="hello", status=JobStatus.COMPLETED,
                 retry_count=2, error="old", duration_seconds=7.0, generated_output_path=str(missing))
    repo.upsert_jobs(project_id, [row])
    restored = repo.restore_jobs(project_id, output_dir=tmp_path)
    assert repo.full_reads == 2  # The re-read is required after the DB reset.
    assert restored[0].status == JobStatus.PENDING
    assert restored[0].retry_count == 0
    assert restored[0].error is None
    assert restored[0].duration_seconds == 0
    assert restored[0].generated_output_path is None
    with repo.database.connect() as connection:
        actual = connection.execute("SELECT status, retry_count, output_path FROM jobs WHERE project_id=?", (project_id,)).fetchone()
    assert tuple(actual) == ("pending", 0, None)


def test_interrupted_job_still_resets_before_hydration(tmp_path):
    repo, project_id = repository(tmp_path)
    repo.upsert_jobs(project_id, [TTSJob(row_number=9, filename="running", text="row")])
    with repo.database.transaction() as connection:
        connection.execute("UPDATE jobs SET status='running' WHERE project_id=?", (project_id,))
    restored = repo.restore_jobs(project_id, output_dir=tmp_path)
    assert repo.full_reads == 1
    assert restored[0].status == JobStatus.PENDING


def test_restore_without_output_dir_remains_single_read(tmp_path):
    repo, project_id = repository(tmp_path)
    repo.upsert_jobs(project_id, [TTSJob(row_number=1, filename="one", text="row")])
    assert len(repo.restore_jobs(project_id)) == 1
    assert repo.full_reads == 1


def test_gui_csv_initial_load_renders_once_without_skipping_range_or_preflight():
    main = (Path(__file__).resolve().parents[1] / "app/gui/main.py").read_text(encoding="utf-8")
    tree = ast.parse(main)
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    functions = {node.name: ast.get_source_segment(main, node) for node in window.body if isinstance(node, ast.FunctionDef)}
    assert "self.reset_row_range_controls(refresh=False)" in functions["load_csv"]
    assert "self.render_queue(); self.refresh_monitor_queue(); self.invalidate_preflight()" in functions["load_csv"]
    assert "self.apply_row_range(refresh=refresh)" in functions["reset_row_range_controls"]
    assert "if refresh: self.render_queue(); self.refresh_monitor_queue(); self.dashboard(); self.invalidate_preflight()" in functions["apply_row_range"]
    assert "self.reset_row_range_controls()" in functions["close_project"]
    assert "self.generation_controller.set_row_range(start,end)" in functions["apply_row_range"]
    assert "self.generation_controller.set_display_range(start,end)" in functions["apply_row_range"]
