from pathlib import Path

import pytest

from app.csv_loader import load_jobs
from app.exceptions import CSVValidationError


def test_load_valid_csv(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("filename,text\n001.mp3,Hej\n", encoding="utf-8")
    jobs = load_jobs(path)
    assert len(jobs) == 1
    assert jobs[0].text == "Hej"
    assert jobs[0].filename == "001.mp3"


def test_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("name,content\n001,Hej\n", encoding="utf-8")
    with pytest.raises(CSVValidationError):
        load_jobs(path)
