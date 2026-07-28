from __future__ import annotations

from pathlib import Path

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.docx import DocxReader
from app.services.text_sources.html_reader import HtmlReader
from app.services.text_sources.markdown import MarkdownReader
from app.services.text_sources.odt import OdtReader
from app.services.text_sources.plain import PlainTextReader
from app.services.text_sources.rtf import RtfReader


class TextReaderFactory:
    def __init__(self, readers: tuple[TextDocumentReader, ...] | None = None) -> None:
        self._readers = readers or (
            PlainTextReader(),
            MarkdownReader(),
            RtfReader(),
            DocxReader(),
            HtmlReader(),
            OdtReader(),
        )
        self._by_extension = {
            extension: reader
            for reader in self._readers
            for extension in reader.extensions
        }

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset(self._by_extension)

    def reader_for(self, path: Path) -> TextDocumentReader:
        suffix = path.suffix.lower()
        try:
            return self._by_extension[suffix]
        except KeyError as exc:
            raise ValueError(f"Unsupported text document: {suffix or 'no extension'}") from exc

    def read(self, path: Path) -> str:
        return self.reader_for(path).read(path)
