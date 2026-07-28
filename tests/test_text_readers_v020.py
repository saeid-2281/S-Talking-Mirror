from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.services.text_source_service import SUPPORTED_TEXT_EXTENSIONS, TextSourceService
from app.services.text_sources import (
    ClipboardReader,
    DocxReader,
    HtmlReader,
    MarkdownReader,
    OdtReader,
    PlainTextReader,
    RtfReader,
    TextReaderFactory,
)


def test_text_reader_factory_registers_independent_readers() -> None:
    factory = TextReaderFactory()

    assert isinstance(factory.reader_for(Path("lesson.txt")), PlainTextReader)
    assert isinstance(factory.reader_for(Path("lesson.md")), MarkdownReader)
    assert isinstance(factory.reader_for(Path("lesson.rtf")), RtfReader)
    assert isinstance(factory.reader_for(Path("lesson.docx")), DocxReader)
    assert isinstance(factory.reader_for(Path("lesson.html")), HtmlReader)
    assert isinstance(factory.reader_for(Path("lesson.odt")), OdtReader)
    assert {".txt", ".md", ".rtf", ".docx", ".html", ".odt"} <= SUPPORTED_TEXT_EXTENSIONS


def test_factory_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unsupported text document"):
        TextReaderFactory().reader_for(Path("book.epub"))


def test_rtf_reader_normalizes_paragraph_spacing_tabs_hex_and_unicode(tmp_path: Path) -> None:
    path = tmp_path / "danish.rtf"
    path.write_text(
        r"{\rtf1\ansi First\par Second\line Tredje\tab kolonne\par \u248? \u230? \u229? \'e6}",
        encoding="cp1252",
    )

    value = RtfReader().read(path)

    assert value == "First\nSecond\nTredje\tkolonne\nø æ å æ"
    assert not any(line.startswith(" ") for line in value.splitlines())


def test_html_reader_ignores_script_and_preserves_blocks(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<html><body><h1>Title</h1><p>First <strong>paragraph</strong>.</p>"
        "<script>ignored()</script><p>Second.</p></body></html>",
        encoding="utf-8",
    )

    value = HtmlReader().read(path)

    assert "Title" in value
    assert "First paragraph." in value
    assert "Second." in value
    assert "ignored" not in value


def test_odt_reader_extracts_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "document.odt"
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        '<office:body><office:text>'
        '<text:h>Heading</text:h><text:p>First paragraph</text:p><text:p>Second paragraph</text:p>'
        '</office:text></office:body></office:document-content>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", content)

    assert OdtReader().read(path) == "Heading\n\nFirst paragraph\n\nSecond paragraph"


def test_clipboard_reader_and_service_share_normalization() -> None:
    reader = ClipboardReader()
    service = TextSourceService(clipboard_reader=reader)

    assert reader.read_value(" First  \r\nSecond \r\n") == " First\nSecond"
    entries = service.entries_from_manual("One\r\n\r\nTwo", split_mode="paragraphs")
    assert [entry.text for entry in entries] == ["One", "Two"]


def test_reader_architecture_keeps_format_parsing_out_of_facade() -> None:
    facade = Path("app/services/text_source_service.py").read_text(encoding="utf-8")
    package = Path("app/services/text_sources")

    assert package.joinpath("factory.py").exists()
    assert package.joinpath("rtf.py").exists()
    assert package.joinpath("docx.py").exists()
    assert "zipfile" not in facade
    assert "ElementTree" not in facade
    assert "_strip_rtf" not in facade
