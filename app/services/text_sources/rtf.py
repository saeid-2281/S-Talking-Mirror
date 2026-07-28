from __future__ import annotations

import html
import re
from pathlib import Path

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text, decode_text

_HEX_ESCAPE = re.compile(r"\\'([0-9a-fA-F]{2})")
_UNICODE_ESCAPE = re.compile(r"\\u(-?\d+)\??")
_DESTINATION_GROUP = re.compile(
    r"{\\(?:fonttbl|colortbl|stylesheet|info|pict|object|header|footer)\b.*?}",
    flags=re.DOTALL,
)
_CONTROL_WORD = re.compile(r"\\[a-zA-Z]+-?\d* ?")
_CONTROL_SYMBOL = re.compile(r"\\[^a-zA-Z0-9\s]")


class RtfReader(TextDocumentReader):
    extensions = frozenset({".rtf"})

    def read(self, path: Path) -> str:
        value = decode_text(path.read_bytes())
        value = _DESTINATION_GROUP.sub("", value)
        value = re.sub(r"\\(?:par|pard|line)\b\s*", "\n", value)
        value = re.sub(r"\\tab\b\s*", "\t", value)
        value = value.replace(r"\~", " ").replace(r"\_", "-")
        value = _HEX_ESCAPE.sub(self._decode_hex, value)
        value = _UNICODE_ESCAPE.sub(self._decode_unicode, value)
        value = _CONTROL_WORD.sub("", value)
        value = _CONTROL_SYMBOL.sub("", value)
        value = value.replace("{", "").replace("}", "")
        return clean_text(html.unescape(value), trim_each_line=True)

    @staticmethod
    def _decode_hex(match: re.Match[str]) -> str:
        raw = bytes([int(match.group(1), 16)])
        return raw.decode("cp1252", errors="replace")

    @staticmethod
    def _decode_unicode(match: re.Match[str]) -> str:
        codepoint = int(match.group(1))
        if codepoint < 0:
            codepoint += 65536
        try:
            return chr(codepoint)
        except ValueError:
            return "�"
