from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt

from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.services.text_source_service import TextSourceService


def test_workspace_builds_and_edits_manual_chunks(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(
        TextSourceService(),
        session_path=tmp_path / "session.json",
    )
    workspace.set_manual_text("First sentence. Second sentence.")

    assert workspace.chunk_table.rowCount() >= 1
    assert workspace.entries
    assert workspace.import_button.isEnabled()

    workspace.chunk_table.selectRow(0)
    qt_app.processEvents()
    workspace.text_editor.setPlainText("Edited chunk")
    workspace._commit_editor()

    assert workspace.entries[0].text == "Edited chunk"
    assert workspace.chunk_table.item(0, 2).text() == "12"


def test_workspace_session_round_trip(qt_app, tmp_path: Path) -> None:
    session = tmp_path / "text-studio-session.json"
    original = TextStudioWorkspace(TextSourceService(), session_path=session)
    original.set_manual_text("Alpha paragraph.\n\nBeta paragraph.")
    original.source_label.setText("Book project")
    original.save_session()

    restored = TextStudioWorkspace(TextSourceService(), session_path=session)

    assert restored.manual_text.toPlainText().startswith("Alpha")
    assert restored.source_label.text() == "Book project"
    assert len(restored.entries) == len(original.entries)


def test_workspace_merge_and_import_signal(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "session.json")
    workspace.split_mode.setCurrentIndex(workspace.split_mode.findData("sentences"))
    workspace.set_manual_text("One. Two. Three.")
    selection = workspace.chunk_table.selectionModel()
    for row in (0, 1):
        index = workspace.chunk_table.model().index(row, 0)
        selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
    workspace.merge_selected()

    assert workspace.chunk_table.rowCount() == 2

    captured: list[tuple[object, str]] = []
    workspace.import_requested.connect(lambda entries, label: captured.append((entries, label)))
    workspace._emit_import()

    assert captured
    entries, label = captured[0]
    assert entries
    assert label == "Text Studio"


def test_workspace_can_disable_jobs(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "session.json")
    workspace.split_mode.setCurrentIndex(workspace.split_mode.findData("sentences"))
    workspace.set_manual_text("One. Two.")
    item = workspace.chunk_table.item(0, 0)
    item.setCheckState(Qt.Unchecked)

    assert len(workspace.entries) == 1
