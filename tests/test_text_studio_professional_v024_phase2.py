from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import Qt

from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.services.text_source_service import TextSourceService
from app.services.text_sources import EpubReader


def _write_epub(path: Path) -> None:
    container = ('<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')
    package = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
               '<manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="two" href="two.xhtml" media-type="application/xhtml+xml"/></manifest>'
               '<spine><itemref idref="one"/><itemref idref="two"/></spine></package>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/one.xhtml", "<html><body><h1>First</h1><p>Alpha.</p></body></html>")
        archive.writestr("OEBPS/two.xhtml", "<html><body><h1>Second</h1><p>Beta.</p></body></html>")


def test_epub_exposes_selectable_chapters(tmp_path: Path) -> None:
    path = tmp_path / "book.epub"
    _write_epub(path)
    sections = EpubReader().read_sections(path)
    assert [section.label for section in sections] == ["First", "Second"]
    assert [section.index for section in sections] == [1, 2]


def test_workspace_can_disable_one_document_section(qt_app, tmp_path: Path) -> None:
    path = tmp_path / "book.epub"
    _write_epub(path)
    workspace = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "session.json")
    workspace.split_mode.setCurrentIndex(workspace.split_mode.findData("single"))
    workspace.add_paths([path])
    root = workspace.file_list.topLevelItem(0)
    assert root.childCount() == 2
    root.child(1).setCheckState(0, Qt.Unchecked)
    qt_app.processEvents()
    assert len(workspace.selected_document_sections()) == 1
    assert len(workspace.entries) == 1
    assert "First" in workspace.entries[0].text


def test_workspace_metrics_include_configured_cost(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "session.json")
    workspace.set_manual_text("A" * 1000)
    workspace.price_per_million.setValue(200.0)
    workspace.characters_per_minute.setValue(1000)
    workspace._update_metrics()
    assert "estimated cost 0.20" in workspace.metrics.text()
    assert "estimated audio 1m 0s" in workspace.metrics.text()


def test_workspace_reorders_one_selected_chunk(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "session.json")
    workspace.split_mode.setCurrentIndex(workspace.split_mode.findData("sentences"))
    workspace.set_manual_text("One. Two.")
    first = workspace.entries[0].text
    workspace.chunk_table.selectRow(0)
    workspace.move_selected(1)
    assert workspace.entries[1].text == first
