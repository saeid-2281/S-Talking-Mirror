from pathlib import Path

import pytest

from app.csv_loader import (
    diagnose_csv,
    file_sha256,
    generate_repaired_preview,
    load_jobs,
    load_valid_jobs,
    save_manual_repair,
)
from app.exceptions import CSVValidationError


def test_load_valid_csv(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("filename,text\n001.mp3,Hej\n", encoding="utf-8")
    jobs = load_jobs(path)
    assert len(jobs) == 1
    assert jobs[0].text == "Hej"
    assert jobs[0].filename == "001.mp3"
    assert jobs[0].source_physical_row == 2
    assert jobs[0].import_status == "imported"


def test_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("name,content\n001,Hej\n", encoding="utf-8")
    with pytest.raises(CSVValidationError):
        load_jobs(path)


def test_semicolon_tab_bom_danish_unicode_and_quoted_delimiters(tmp_path: Path) -> None:
    semicolon = tmp_path / "semicolon.csv"
    semicolon.write_text('filename;text\næøå.mp3;"Hej, verden; stadig tekst"\n', encoding="utf-8")
    tab = tmp_path / "tab.csv"
    tab.write_text("filename\ttext\n001.mp3\t\"Linje 1\nLinje 2; med semikolon\"\n", encoding="utf-8-sig")

    semicolon_state = diagnose_csv(semicolon)
    tab_jobs = load_jobs(tab)

    assert semicolon_state.detected_delimiter == ";"
    assert semicolon_state.jobs[0].filename == "æøå.mp3"
    assert semicolon_state.jobs[0].text == "Hej, verden; stadig tekst"
    assert diagnose_csv(tab).detected_encoding == "utf-8-sig"
    assert tab_jobs[0].text == "Linje 1\nLinje 2; med semikolon"


def test_extra_unquoted_delimiter_rejects_row_without_field_shift(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("filename,text\n001.mp3,Dette er tekst, med ukvoteret komma\n", encoding="utf-8")

    state = diagnose_csv(path)

    assert state.rejected_rows == 1
    assert state.extra_column_rows == [2]
    assert state.jobs == []
    with pytest.raises(CSVValidationError):
        load_jobs(path)


def test_missing_field_and_extra_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("filename,text\n001.mp3\n002.mp3,Hej,extra\n", encoding="utf-8")

    state = diagnose_csv(path)

    assert state.rejected_rows == 2
    assert state.missing_column_rows == [2]
    assert state.extra_column_rows == [3]


def test_swapped_looking_values_are_not_auto_swapped(tmp_path: Path) -> None:
    path = tmp_path / "swapped.csv"
    path.write_text("filename,text\nDette er prose i filename,001.mp3\n", encoding="utf-8")

    state = diagnose_csv(path)

    assert state.rejected_rows == 1
    assert state.filename_looks_like_prose_rows == [2]
    assert state.text_looks_like_filename_rows == [2]
    assert state.jobs == []


def test_valid_text_punctuation_does_not_affect_filename(tmp_path: Path) -> None:
    path = tmp_path / "valid.csv"
    text = '"Lang dansk tekst med /, ?, :, og citater; men korrekt quoted."'
    path.write_text(f"filename,text\nd0-l01-a.mp3,{text}\n", encoding="utf-8")

    state = diagnose_csv(path)

    assert state.rejected_rows == 0
    assert state.jobs[0].filename == "d0-l01-a.mp3"
    assert "/" in state.jobs[0].text


def test_repaired_preview_original_unchanged_rejected_rows_and_manual_repair(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("filename,text\n001.mp3,Hej\nDette er prose filename,002.mp3\n", encoding="utf-8")
    original_hash = file_sha256(path)
    state = diagnose_csv(path)

    repaired, rejected = generate_repaired_preview(state)
    fixed = save_manual_repair(state, text="Repareret dansk tekst", filename="002.mp3")

    assert repaired.exists()
    assert rejected and rejected.exists()
    assert fixed.filename == "002.mp3"
    assert file_sha256(path) == original_hash
    assert "Repareret dansk tekst" in repaired.read_text(encoding="utf-8")


def test_duplicate_filename_prevention_and_import_valid_rows_only(tmp_path: Path) -> None:
    path = tmp_path / "mixed.csv"
    path.write_text("filename,text\n001.mp3,Hej\nProse filename value,002.mp3\n", encoding="utf-8")
    state = diagnose_csv(path)

    jobs = load_valid_jobs(path)

    assert len(jobs) == 1
    with pytest.raises(CSVValidationError):
        save_manual_repair(state, text="Ny tekst", filename="001.mp3")


def test_regression_field_drift_modeled_on_4212_row_issue(tmp_path: Path) -> None:
    path = tmp_path / "drift.csv"
    paragraph = "Dette er en meget lang dansk tekst, med kommaer, og flere sætninger, som burde være quoted."
    path.write_text(f"filename,text\n001.mp3,{paragraph}\n", encoding="utf-8")

    state = diagnose_csv(path)

    assert state.rejected_rows == 1
    assert state.extra_column_rows == [2]
    assert state.jobs == []
