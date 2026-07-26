from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.csv_loader import diagnose_csv, file_sha256
from app.exceptions import CSVValidationError
from app.gui.main import MainWindow
from app.services.csv_repair_service import (
    CsvRepairSession,
    expand_filename_template,
    increment_numeric_suffix,
)


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def _repair_source(tmp_path: Path) -> Path:
    path = tmp_path / "input.csv"
    rows = [
        ["filename", "text"],
        ["d0-l01-001.mp3", "Tekst 1"],
        ["Dette er ikke et filnavn men lang prosa", "Tekst 2"],
        ["d0-l01-003.mp3", "Tekst 3"],
        ["Dette er heller ikke et filnavn", "Tekst 4"],
        ["d0-l01-005.mp3", "Tekst 5"],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    return path


def test_neighboring_filename_pattern_detection(tmp_path: Path) -> None:
    state = diagnose_csv(_repair_source(tmp_path))
    session = CsvRepairSession(state, project_name="Danish Lessons")

    pattern = session.pattern_for_row(3)
    suggestion, suggested_pattern = session.suggest_from_neighbors(3)

    assert pattern.prefix == "d0-l01-"
    assert pattern.width == 3
    assert pattern.extension == ".mp3"
    assert pattern.confidence == "high"
    assert suggested_pattern.confidence == "high"
    assert suggestion == "d0-l01-002.mp3"


def test_sequential_suffix_generation_and_template_expansion() -> None:
    assert increment_numeric_suffix("chapter-001.mp3") == "chapter-002.mp3"
    assert expand_filename_template(
        "{project}-{index:03d}{ext}",
        row=42,
        index=7,
        project="Danish Lessons",
        original_stem="input",
        ext=".mp3",
    ) == "Danish-Lessons-007.mp3"


def test_duplicate_prevention_and_invalid_extension_rejection(tmp_path: Path) -> None:
    state = diagnose_csv(_repair_source(tmp_path))
    session = CsvRepairSession(state)

    duplicate = session.batch_preview([3], template="d0-l01-001{ext}", extension=".mp3")
    invalid = session.batch_preview([3], template="fixed{ext}", extension=".txt")

    assert "existing valid filename" in duplicate[0].conflict
    assert "unsupported extension" in invalid[0].conflict
    with pytest.raises(CSVValidationError):
        session.apply_batch([3], template="d0-l01-001{ext}", extension=".mp3")


def test_batch_preview_apply_and_undo_redo(tmp_path: Path) -> None:
    state = diagnose_csv(_repair_source(tmp_path))
    session = CsvRepairSession(state, project_name="Danish Lessons")
    rows = [repair.physical_row for repair in session.repairs]

    preview = session.batch_preview(rows, template="{project}-{index:03d}{ext}", extension=".mp3")
    changed = session.apply_batch(rows, template="{project}-{index:03d}{ext}", extension=".mp3")

    assert [row.proposed_filename for row in preview] == ["Danish-Lessons-001.mp3", "Danish-Lessons-002.mp3"]
    assert changed == 2
    assert session.unresolved_count == 0
    assert session.repairs[0].filename == "Danish-Lessons-001.mp3"
    assert session.undo()
    assert session.repairs[0].filename == session.repairs[0].old_filename
    assert session.redo()
    assert session.repairs[0].filename == "Danish-Lessons-001.mp3"


def test_save_repaired_csv_original_unchanged_order_text_and_audit(tmp_path: Path) -> None:
    source = _repair_source(tmp_path)
    original_hash = file_sha256(source)
    state = diagnose_csv(source)
    original_text_by_row = {
        job.row_number: job.text for job in state.jobs
    } | {repair.physical_row: repair.text for repair in CsvRepairSession(state).repairs}
    session = CsvRepairSession(state, project_name="Danish Lessons")
    rows = [repair.physical_row for repair in session.repairs]
    session.apply_batch(rows, template="fixed-{index:03d}{ext}", extension=".mp3")

    result = session.save_repaired_csv(tmp_path / "input.repaired.csv", tmp_path / "reports")

    assert file_sha256(source) == original_hash
    assert result.repaired_csv_path.exists()
    assert result.diagnostics.rejected_rows == 0
    assert result.diagnostics.valid_rows == 5
    assert [job.row_number for job in result.diagnostics.jobs] == [2, 3, 4, 5, 6]
    assert {job.row_number: job.text for job in result.diagnostics.jobs} == original_text_by_row
    assert result.audit_json_path.exists()
    assert result.audit_csv_path.exists()
    payload = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
    assert payload["original_source_hash"] == original_hash
    assert payload["repaired_file_hash"] == result.repaired_hash


def test_project_path_replacement_queue_reload_diagnostics_and_preflight(qt_app, tmp_path: Path) -> None:
    source = _repair_source(tmp_path)
    state = diagnose_csv(source)
    session = CsvRepairSession(state, project_name="Danish Lessons")
    session.apply_batch([repair.physical_row for repair in session.repairs], template="fixed-{index:03d}{ext}", extension=".mp3")
    repaired = session.save_repaired_csv(tmp_path / "input.repaired.csv", tmp_path / "reports").repaired_csv_path
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    window.project_controller.new_project("Danish Lessons", source, tmp_path / "out", window.settings())

    window.replace_project_csv_with_repaired(repaired)

    assert window.csv.text() == str(repaired)
    assert context.project_controller.current_project.csv_path == repaired
    assert len(window.generation_controller.jobs) == 5
    assert context.preflight_service.latest is not None
    assert context.preflight_service.latest.status in {"Ready", "Ready with warnings"}
