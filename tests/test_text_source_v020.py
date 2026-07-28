from __future__ import annotations

import csv
import zipfile
from pathlib import Path

from app.services.text_source_service import TextSourceService


def test_manual_text_can_be_split_and_written_as_normalized_csv(tmp_path: Path) -> None:
    service = TextSourceService()
    entries = service.entries_from_manual(
        "First paragraph.\n\nSecond paragraph.",
        split_mode="paragraphs",
        filename_prefix="lesson",
        start_index=4,
        extension=".mp3",
    )

    assert [entry.filename for entry in entries] == ["lesson-004.mp3", "lesson-005.mp3"]
    assert [entry.text for entry in entries] == ["First paragraph.", "Second paragraph."]

    path = service.write_normalized_csv(entries, tmp_path, label="Manual lesson")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["text"] == "First paragraph."
    assert rows[1]["filename"] == "lesson-005.mp3"


def test_text_documents_support_txt_markdown_rtf_docx_html_and_odt(tmp_path: Path) -> None:
    service = TextSourceService()
    txt = tmp_path / "plain.txt"
    md = tmp_path / "notes.md"
    rtf = tmp_path / "formatted.rtf"
    docx = tmp_path / "document.docx"
    html = tmp_path / "page.html"
    odt = tmp_path / "document.odt"
    txt.write_text("Plain text", encoding="utf-8")
    md.write_text("# Heading\n\nMarkdown text", encoding="utf-8")
    rtf.write_text(r"{\rtf1\ansi First\par Second}", encoding="cp1252")
    html.write_text("<h1>Heading</h1><p>HTML text</p>", encoding="utf-8")
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Word paragraph</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    odt_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        '<office:body><office:text><text:p>ODT paragraph</text:p></office:text></office:body>'
        '</office:document-content>'
    )
    with zipfile.ZipFile(odt, "w") as archive:
        archive.writestr("content.xml", odt_xml)

    assert service.read_text_file(txt) == "Plain text"
    assert "Markdown text" in service.read_text_file(md)
    assert service.read_text_file(rtf) == "First\nSecond"
    assert service.read_text_file(docx) == "Word paragraph"
    assert "HTML text" in service.read_text_file(html)
    assert service.read_text_file(odt) == "ODT paragraph"


def test_multiple_files_keep_source_names_and_unique_sequence(tmp_path: Path) -> None:
    service = TextSourceService()
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_text("A\n\nB", encoding="utf-8")
    second.write_text("C", encoding="utf-8")

    entries = service.entries_from_files([first, second], split_mode="paragraphs", start_index=1)

    assert [entry.filename for entry in entries] == ["one-001.mp3", "one-002.mp3", "two-003.mp3"]
    assert [entry.source_label for entry in entries] == ["one.txt", "one.txt", "two.txt"]


def test_text_source_dialog_and_project_action_are_integrated() -> None:
    main = Path("app/gui/main.py").read_text(encoding="utf-8")
    dialog = Path("app/gui/dialogs/text_source_dialog.py").read_text(encoding="utf-8")

    assert "def add_text_source" in main
    assert "Add text source" in main
    assert "Ctrl+Shift+T" in main
    assert "class TextSourceDialog" in dialog
    assert "Manual text" in dialog
    assert "Text files" in dialog
