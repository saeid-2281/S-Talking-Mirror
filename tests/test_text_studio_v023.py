from __future__ import annotations

import zipfile
from pathlib import Path

from app.services.text_source_service import TextSourceService
from app.services.text_sources import EpubReader, PdfReader, TextReaderFactory


def _write_epub(path: Path) -> None:
    container = (
        '<?xml version="1.0"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        '</rootfiles></container>'
    )
    package = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="chapter"/></spine></package>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/chapter.xhtml", "<html><body><h1>Title</h1><p>Chapter text.</p></body></html>")


def test_epub_reader_follows_spine_order(tmp_path: Path) -> None:
    path = tmp_path / "book.epub"
    _write_epub(path)

    assert EpubReader().read(path) == "Title\nChapter text."


def test_factory_registers_pdf_and_epub() -> None:
    factory = TextReaderFactory()

    assert isinstance(factory.reader_for(Path("book.epub")), EpubReader)
    assert isinstance(factory.reader_for(Path("paper.pdf")), PdfReader)


def test_smart_chunking_respects_requested_limit() -> None:
    service = TextSourceService()
    text = "First sentence is short. Second sentence is also short. Third sentence finishes the paragraph."

    chunks = service.split_text(text, "smart", max_characters=55)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 55 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ") == text


def test_text_studio_metrics_estimate_duration_and_cost() -> None:
    service = TextSourceService()
    entries = service.entries_from_manual("A" * 900, max_characters=0)

    metrics = service.metrics(entries, characters_per_minute=900, price_per_million_characters=200)

    assert metrics.jobs == 1
    assert metrics.characters == 900
    assert metrics.estimated_seconds == 60
    assert round(metrics.estimated_cost, 4) == 0.18


def test_text_studio_dialog_contains_review_controls() -> None:
    source = Path("app/gui/dialogs/text_source_dialog.py").read_text(encoding="utf-8")

    assert 'setWindowTitle("Text Studio")' in source
    assert "Smart chunks" in source
    assert "Enable all" in source
    assert "Estimated audio" in source
    assert "*.epub *.pdf" in source
