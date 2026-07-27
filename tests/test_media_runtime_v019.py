from __future__ import annotations

import os
from pathlib import Path

from app.config.media_runtime import (
    KNOWN_BENIGN_FFMPEG_MESSAGES,
    configure_media_runtime,
    is_known_benign_ffmpeg_message,
)


def test_known_mp3_timestamp_messages_are_benign() -> None:
    for message in KNOWN_BENIGN_FFMPEG_MESSAGES:
        assert is_known_benign_ffmpeg_message(f"[mp3float] {message}")
    assert not is_known_benign_ffmpeg_message("Invalid data found when processing input")


def test_media_runtime_keeps_ffmpeg_as_safe_default(monkeypatch) -> None:
    monkeypatch.delenv("S_TALKING_MEDIA_BACKEND", raising=False)
    monkeypatch.delenv("QT_MEDIA_BACKEND", raising=False)
    result = configure_media_runtime()
    assert result.backend == "ffmpeg"
    assert os.environ["QT_MEDIA_BACKEND"] == "ffmpeg"


def test_windows_backend_can_be_selected_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("S_TALKING_MEDIA_BACKEND", "windows")
    monkeypatch.delenv("QT_MEDIA_BACKEND", raising=False)
    result = configure_media_runtime()
    assert result.backend == "windows"
    assert os.environ["QT_MEDIA_BACKEND"] == "windows"


def test_normal_launcher_is_windowed_and_console_launcher_is_available() -> None:
    run = Path("scripts/run.ps1").read_text(encoding="utf-8")
    console = Path("scripts/run-console.ps1").read_text(encoding="utf-8")
    assert "pythonw.exe" in run
    assert "-MediaBackend" in run
    assert "-Console" in console
