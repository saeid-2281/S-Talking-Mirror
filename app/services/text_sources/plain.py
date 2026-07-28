from __future__ import annotations

from pathlib import Path

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text, decode_text


class PlainTextReader(TextDocumentReader):
    extensions = frozenset({".txt", ".text"})

    def read(self, path: Path) -> str:
        return clean_text(decode_text(path.read_bytes()))


class ClipboardReader:
    """Normalizes text pasted or typed by the user."""

    def read_value(self, value: str) -> str:
        return clean_text(value)
