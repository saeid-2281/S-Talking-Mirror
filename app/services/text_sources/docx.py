from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text


class DocxReader(TextDocumentReader):
    extensions = frozenset({".docx"})
    _namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def read(self, path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError("The DOCX file is damaged or is not a valid Word document.") from exc

        try:
            root = ElementTree.fromstring(document)
        except ElementTree.ParseError as exc:
            raise ValueError("The DOCX document XML is invalid.") from exc

        paragraphs: list[str] = []
        for paragraph in root.iter(f"{self._namespace}p"):
            parts: list[str] = []
            for node in paragraph.iter():
                if node.tag == f"{self._namespace}t" and node.text:
                    parts.append(node.text)
                elif node.tag == f"{self._namespace}tab":
                    parts.append("\t")
                elif node.tag in {f"{self._namespace}br", f"{self._namespace}cr"}:
                    parts.append("\n")
            value = "".join(parts).strip()
            if value:
                paragraphs.append(value)
        return clean_text("\n\n".join(paragraphs))
