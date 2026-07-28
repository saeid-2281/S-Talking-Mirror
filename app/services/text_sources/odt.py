from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text

_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class OdtReader(TextDocumentReader):
    extensions = frozenset({".odt"})

    def read(self, path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as archive:
                document = archive.read("content.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError("The ODT file is damaged or is not a valid OpenDocument file.") from exc

        try:
            root = ElementTree.fromstring(document)
        except ElementTree.ParseError as exc:
            raise ValueError("The ODT content XML is invalid.") from exc

        paragraphs: list[str] = []
        for element in root.iter():
            if element.tag not in {f"{_TEXT_NS}p", f"{_TEXT_NS}h"}:
                continue
            value = "".join(element.itertext()).strip()
            if value:
                paragraphs.append(value)
        return clean_text("\n\n".join(paragraphs))
