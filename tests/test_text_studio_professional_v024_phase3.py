from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt

from app.gui.widgets.text_studio_workspace import ReorderableChunkTable, TextStudioWorkspace
from app.services.text_source_service import TextSourceService


def _workspace(tmp_path: Path) -> TextStudioWorkspace:
    workspace = TextStudioWorkspace(
        TextSourceService(),
        session_path=tmp_path / "autosave.json",
    )
    workspace.split_mode.setCurrentIndex(workspace.split_mode.findData("sentences"))
    workspace.set_manual_text("One. Two. Three. Four.")
    return workspace


def _select_rows(workspace: TextStudioWorkspace, rows: tuple[int, ...]) -> None:
    selection = workspace.chunk_table.selectionModel()
    selection.clearSelection()
    for row in rows:
        index = workspace.chunk_table.model().index(row, 0)
        selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)


def test_chunk_table_supports_internal_reorder_requests(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert isinstance(workspace.chunk_table, ReorderableChunkTable)
    original = [entry.text for entry in workspace._entries]

    workspace.chunk_table.item(0, 0).setCheckState(Qt.Unchecked)
    workspace.reorder_rows([0, 1], 4)

    assert [entry.text for entry in workspace._entries] == original[2:] + original[:2]
    assert workspace.chunk_table.item(2, 0).checkState() == Qt.Unchecked


def test_multiple_selected_chunks_can_be_split(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "autosave.json")
    workspace.max_characters.setValue(8)
    workspace._entries = [
        workspace.service.entries_from_manual(
            "Alpha beta gamma.",
            filename_prefix="a",
            max_characters=0,
        )[0],
        workspace.service.entries_from_manual(
            "Delta epsilon zeta.",
            filename_prefix="b",
            max_characters=0,
        )[0],
    ]
    workspace._render_entries()
    _select_rows(workspace, (0, 1))

    workspace.split_selected()

    assert len(workspace._entries) > 2
    assert all(entry.character_count <= 8 for entry in workspace._entries)


def test_selected_chunks_can_be_enabled_and_disabled(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _select_rows(workspace, (0, 1))

    workspace._set_selected_enabled(False)
    assert workspace.chunk_table.item(0, 0).checkState() == Qt.Unchecked
    assert workspace.chunk_table.item(1, 0).checkState() == Qt.Unchecked
    assert len(workspace.entries) == 2

    workspace._set_selected_enabled(True)
    assert len(workspace.entries) == 4


def test_portable_session_export_and_import_round_trip(qt_app, tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    source.source_label.setText("Portable book")
    source.chunk_table.item(1, 0).setCheckState(Qt.Unchecked)
    exported = source.export_session(tmp_path / "portable-session.json")

    restored = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "other.json")
    assert restored.import_session(exported)
    assert restored.source_label.text() == "Portable book"
    assert [entry.text for entry in restored._entries] == [entry.text for entry in source._entries]
    assert restored.chunk_table.item(1, 0).checkState() == Qt.Unchecked


def test_document_section_bulk_actions_are_exposed() -> None:
    source = Path("app/gui/widgets/text_studio_workspace.py").read_text(encoding="utf-8")
    assert "All sections" in source
    assert "No sections" in source
    assert "Invert" in source
    assert "Save session as" in source
    assert "Open session" in source
