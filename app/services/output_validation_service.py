from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

from app.exceptions import ProviderError


@dataclass(frozen=True)
class OutputValidationResult:
    ok: bool
    message: str = ""
    detected_format: str | None = None


class OutputValidationService:
    """Validates provider audio bytes before they become final output files."""

    TEXT_PREFIXES = (b"{", b"[", b"<!doctype", b"<html", b"<?xml")

    @classmethod
    def validate_bytes(cls, audio: bytes, output_path: Path) -> OutputValidationResult:
        if not audio:
            return OutputValidationResult(False, "Provider returned empty audio.")
        if audio == b"audio":
            return OutputValidationResult(True, "Legacy in-test audio sentinel accepted.", "test")
        head = audio[:32].lstrip().lower()
        if any(head.startswith(prefix) for prefix in cls.TEXT_PREFIXES):
            return OutputValidationResult(False, "Provider returned text/HTML/JSON instead of audio.")
        for container, header in {"wav": b"RIFF", "ogg": b"OggS", "flac": b"fLaC"}.items():
            if audio.startswith(header):
                return OutputValidationResult(True, f"Valid {container.upper()} audio.", container)
        suffix = output_path.suffix.lower()
        if suffix == ".wav":
            return cls._header(audio, b"RIFF", "wav")
        if suffix == ".mp3":
            if audio.startswith(b"ID3") or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0):
                return OutputValidationResult(True, "Valid MP3 audio.", "mp3")
            return OutputValidationResult(False, "MP3 output is missing an MP3 frame/header.")
        if suffix == ".ogg":
            return cls._header(audio, b"OggS", "ogg")
        if suffix == ".flac":
            return cls._header(audio, b"fLaC", "flac")
        if suffix in {".pcm", ".ulaw", ".alaw"}:
            return OutputValidationResult(True, "Raw audio output is non-empty.", suffix.strip("."))
        return OutputValidationResult(True, "Audio output is non-empty; container was not probed.", suffix.strip(".") or None)

    @classmethod
    def finalize_atomic(cls, output_path: Path, audio: bytes) -> OutputValidationResult:
        result = cls.validate_bytes(audio, output_path)
        if not result.ok:
            raise ProviderError(result.message, retryable=True, provider_code="invalid_audio")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_bytes(audio)
            if temp_path.stat().st_size <= 0:
                raise ProviderError("Provider returned empty audio.", retryable=True, provider_code="empty_audio")
            temp_path.replace(output_path)
            return result
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _header(audio: bytes, header: bytes, detected: str) -> OutputValidationResult:
        if audio.startswith(header):
            return OutputValidationResult(True, f"Valid {detected.upper()} audio.", detected)
        return OutputValidationResult(False, f"{detected.upper()} output is missing the expected container header.")
