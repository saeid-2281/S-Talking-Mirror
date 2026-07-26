from __future__ import annotations

from pathlib import Path
from openpyxl import Workbook

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.models.project_source import SourceType
from app.services.source_import_service import SourceImportService


def write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    path.write_text("text,filename\n" + "".join(f"{text},{filename}\n" for text, filename in rows), encoding="utf-8")


def test_multiple_csv_sources_merge_with_provenance(tmp_path: Path) -> None:
    one = tmp_path / "one.csv"
    two = tmp_path / "two.tsv"
    write_csv(one, [("Hej", "one.mp3")])
    two.write_text("filename\ttext\n" "two.mp3\tTak\n", encoding="utf-8")
    service = SourceImportService()

    sources = service.create_sources([one, two], project_id=7)
    result = service.import_sources(sources)
    jobs = service.assign_merged_row_numbers(result.jobs)

    assert result.can_import is True
    assert [job.filename for job in jobs] == ["one.mp3", "two.mp3"]
    assert jobs[0].source_id == sources[0].source_id
    assert jobs[1].source_display_name == "two"
    assert jobs[1].source_row == 2
    assert [job.row_number for job in jobs] == [1, 2]


def test_csv_and_xlsx_multiple_sheets(tmp_path: Path) -> None:
    csv_path = tmp_path / "input.csv"
    write_csv(csv_path, [("Hej", "csv.mp3")])
    xlsx_path = tmp_path / "book.xlsx"
    workbook = Workbook()
    active = workbook.active
    active.title = "A"
    active.append(["text", "filename"])
    active.append(["Tak", "a.mp3"])
    sheet = workbook.create_sheet("B")
    sheet.append(["filename", "text"])
    sheet.append(["b.mp3", "En oe"])
    workbook.save(xlsx_path)

    service = SourceImportService()
    sources = service.create_sources([csv_path, xlsx_path])
    result = service.import_sources(sources)

    assert [source.source.worksheet_name for source in result.sources if source.source.source_type == SourceType.XLSX] == ["A", "B"]
    assert [job.filename for job in result.jobs] == ["csv.mp3", "a.mp3", "b.mp3"]
    assert result.jobs[1].source_sheet == "A"
    assert result.jobs[2].source_sheet == "B"


def test_disabled_source_is_not_in_merged_queue(tmp_path: Path) -> None:
    one = tmp_path / "one.csv"
    two = tmp_path / "two.csv"
    write_csv(one, [("Hej", "one.mp3")])
    write_csv(two, [("Tak", "two.mp3")])
    service = SourceImportService()
    sources = service.create_sources([one, two])
    sources[1].enabled = False

    result = service.import_sources(sources)

    assert [job.filename for job in result.jobs] == ["one.mp3"]
    assert result.sources[1].source.valid_rows == 1


def test_cross_source_filename_collision_blocks_import(tmp_path: Path) -> None:
    one = tmp_path / "one.csv"
    two = tmp_path / "two.csv"
    write_csv(one, [("Hej", "same.mp3")])
    write_csv(two, [("Tak", "same.mp3")])
    result = SourceImportService().import_sources(SourceImportService().create_sources([one, two]))

    assert result.can_import is False
    assert result.collisions
    assert result.collisions[0].code == "cross_source_filename_collision"


def test_legacy_xls_is_explicitly_unsupported(tmp_path: Path) -> None:
    source = SourceImportService().create_sources([tmp_path / "legacy.xls"])[0]

    assert source.import_status.value == "unsupported"


def test_source_repository_and_job_provenance_persist(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    container = create_service_container(runtime)
    project = container.project_manager.new_project("Project", None, tmp_path / "out", "mock")
    csv_path = tmp_path / "one.csv"
    write_csv(csv_path, [("Hej", "one.mp3")])
    sources = container.source_import_service.create_sources([csv_path], project_id=project.project_id)
    result = container.source_import_service.import_sources(sources)
    jobs = container.source_import_service.assign_merged_row_numbers(result.jobs)

    container.source_repository.upsert_sources(project.project_id, sources)
    container.job_repository.upsert_jobs(project.project_id, jobs, output_dir=tmp_path / "out")
    restored_sources = container.source_repository.list_by_project(project.project_id)
    restored_jobs = container.job_repository.restore_jobs(project.project_id)

    assert restored_sources[0].source_id == sources[0].source_id
    assert restored_jobs[0].source_id == sources[0].source_id
    assert restored_jobs[0].source_display_name == "one"


def test_migration_adds_source_tables_and_job_columns(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite")
    database.initialize()
    with database.connect() as connection:
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}

    assert {"project_sources", "source_worksheets", "source_import_snapshots", "provider_usage"}.issubset(tables)
    assert {"source_id", "provider_override", "voice_override", "output_subfolder"}.issubset(job_columns)


def test_existing_database_is_backed_up_before_v2_migration(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 2")
        connection.commit()

    Database(tmp_path / "db.sqlite").initialize()

    assert (tmp_path / "db.sqlite.pre-v2.bak").exists()
