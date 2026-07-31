from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text
from app.services.text_sources.document_structure import DocumentSection
from app.services.text_sources.html_reader import _PlainHtmlParser

_CONTAINER = "META-INF/container.xml"
_CONTAINER_NS = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}


class EpubReader(TextDocumentReader):
    """Read EPUB spine documents in reading order using only the standard library."""

    extensions = frozenset({".epub"})

    def read(self, path: Path) -> str:
        sections = self.read_sections(path)
        return clean_text("\n".join(section.text for section in sections))

    def read_sections(self, path: Path) -> list[DocumentSection]:
        try:
            with zipfile.ZipFile(path) as archive:
                rootfile = self._rootfile(archive)
                documents = self._spine_documents(archive, rootfile)
                chapters = [self._read_html(archive, name) for name in documents]
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ValueError("The EPUB file is damaged or has an invalid package structure.") from exc

        sections: list[DocumentSection] = []
        for index, (name, chapter) in enumerate(zip(documents, chapters, strict=True), 1):
            if not chapter:
                continue
            first_line = chapter.splitlines()[0].strip() if chapter.splitlines() else ""
            fallback = Path(name).stem.replace("_", " ").replace("-", " ").strip().title()
            label = first_line[:80] or fallback or f"Chapter {index}"
            sections.append(DocumentSection(str(index), label, chapter, Path(path), index))
        if not sections:
            raise ValueError("The EPUB contains no readable text chapters.")
        return sections

    @staticmethod
    def _rootfile(archive: zipfile.ZipFile) -> str:
        root = ElementTree.fromstring(archive.read(_CONTAINER))
        node = root.find(".//container:rootfile", _CONTAINER_NS)
        if node is None or not node.attrib.get("full-path"):
            raise KeyError("EPUB rootfile")
        return node.attrib["full-path"]

    @staticmethod
    def _spine_documents(archive: zipfile.ZipFile, rootfile: str) -> list[str]:
        package = ElementTree.fromstring(archive.read(rootfile))
        manifest = {
            item.attrib.get("id", ""): item.attrib.get("href", "")
            for item in package.findall(".//opf:manifest/opf:item", _OPF_NS)
        }
        base = posixpath.dirname(rootfile)
        documents: list[str] = []
        for itemref in package.findall(".//opf:spine/opf:itemref", _OPF_NS):
            href = manifest.get(itemref.attrib.get("idref", ""), "")
            if href:
                documents.append(posixpath.normpath(posixpath.join(base, href)))
        return documents

    @staticmethod
    def _read_html(archive: zipfile.ZipFile, name: str) -> str:
        parser = _PlainHtmlParser()
        parser.feed(archive.read(name).decode("utf-8", errors="replace"))
        parser.close()
        value = clean_text("".join(parser.parts), trim_each_line=True)
        return re.sub(r"\n{2,}", "\n", value)
