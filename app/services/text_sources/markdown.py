from __future__ import annotations

import re
from pathlib import Path

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text, decode_text


class MarkdownReader(TextDocumentReader):
    extensions = frozenset({".md", ".markdown"})

    def read(self, path: Path) -> str:
        value = decode_text(path.read_bytes())
        value = re.sub(r"```.*?```", "", value, flags=re.DOTALL)
        value = re.sub(r"`([^`]+)`", r"\1", value)
        value = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
        value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
        value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*>\s?", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*[-+*]\s+", "", value, flags=re.MULTILINE)
        value = re.sub(r"[*_~]{1,3}", "", value)
        return clean_text(value)
