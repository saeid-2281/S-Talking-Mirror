from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import AppSettings, TTSJob


def test_output_extension_is_added() -> None:
    job = TTSJob(row_number=2, text="Hej", filename="001")
    assert job.output_path(Path("out"), ".mp3") == Path("out/001.mp3")


def test_settings_reject_conflicting_file_policy() -> None:
    with pytest.raises(ValidationError):
        AppSettings(skip_existing=True, overwrite_existing=True)
