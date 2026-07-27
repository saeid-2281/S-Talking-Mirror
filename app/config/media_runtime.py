from __future__ import annotations

import os
import sys
from dataclasses import dataclass


KNOWN_BENIGN_FFMPEG_MESSAGES = (
    "Could not update timestamps for skipped samples.",
    "Could not update timestamps for discarded samples.",
)


@dataclass(frozen=True)
class MediaRuntimeConfig:
    backend: str
    console_logging: bool
    reason: str


def configure_media_runtime() -> MediaRuntimeConfig:
    """Configure Qt Multimedia before PySide6.QtMultimedia is imported.

    S Talking keeps Qt's FFmpeg backend as the default because it has the broadest
    codec support. On Windows, users can opt into the native backend with
    ``S_TALKING_MEDIA_BACKEND=windows`` when a particular FFmpeg build emits noisy
    decoder warnings. The normal launcher is windowed, so harmless native decoder
    diagnostics do not leak into the production UI.
    """

    requested = (os.environ.get("S_TALKING_MEDIA_BACKEND") or "").strip().lower()
    if not requested:
        requested = "ffmpeg"

    allowed = {"ffmpeg", "windows", "darwin", "gstreamer", "android"}
    if requested not in allowed:
        requested = "ffmpeg"

    # Must be set before importing QtMultimedia.
    os.environ.setdefault("QT_MEDIA_BACKEND", requested)

    # Explicitly keep developer-level FFmpeg logging disabled unless the user
    # deliberately opted in. Qt documents both switches as diagnostic controls.
    if os.environ.get("S_TALKING_MEDIA_DEBUG", "0") not in {"1", "true", "yes"}:
        os.environ.pop("QT_FFMPEG_DEBUG", None)
        rules = os.environ.get("QT_LOGGING_RULES", "")
        if "ffmpeg" not in rules.lower() and "multimedia" not in rules.lower():
            os.environ.setdefault(
                "QT_LOGGING_RULES",
                "qt.multimedia.ffmpeg.*=false;*.multimedia.*.debug=false",
            )

    console_logging = os.environ.get("S_TALKING_GUI_CONSOLE", "0") in {"1", "true", "yes"}
    if requested == "windows" and sys.platform == "win32":
        reason = "Native Windows media backend selected by user override."
    elif requested == "ffmpeg":
        reason = "Qt FFmpeg backend selected for broad codec support."
    else:
        reason = f"Qt media backend selected: {requested}."
    return MediaRuntimeConfig(requested, console_logging, reason)


def is_known_benign_ffmpeg_message(message: str) -> bool:
    """Return True for Qt/FFmpeg MP3 gapless-timestamp warnings.

    These warnings are emitted while FFmpeg applies encoder delay/padding from
    MP3 gapless metadata. They are not synthesis failures and must not reduce
    application health or mark generated audio as invalid.
    """

    text = str(message or "")
    return any(token in text for token in KNOWN_BENIGN_FFMPEG_MESSAGES)
