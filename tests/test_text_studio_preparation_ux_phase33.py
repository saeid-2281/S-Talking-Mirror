from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.text_studio_quality import TextStudioQualityPanel
from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.services.text_source_service import TextSourceEntry, TextSourceService
from app.services.text_studio_quality import (
    analyze_text_studio_entries,
    normalize_reading_text,
    renumber_entry_filenames,
    replace_entry_text,
)


def _workspace(tmp_path: Path) -> TextStudioWorkspace:
    return TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "text-studio.json")


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase33_whitespace_normalization_preserves_paragraphs() -> None:
    value = "  First   line.  \n\n\n  Second\tline.  "
    assert normalize_reading_text(value) == "First line.\n\nSecond line."


def test_phase33_quality_analysis_separates_blocking_issues_and_warnings() -> None:
    entries = [
        TextSourceEntry("Same text", "same.mp3", "A"),
        TextSourceEntry("Same   text", "same.mp3", "B"),
        TextSourceEntry("A" * 30, "third.mp3", "C"),
    ]
    summary = analyze_text_studio_entries(entries, enabled=[True, True, True], max_characters=20)

    assert summary.duplicate_filenames == 2
    assert summary.duplicate_texts == 2
    assert summary.oversized_chunks == 1
    assert summary.blocking_issues == 2
    assert summary.warnings >= 3
    assert summary.ready_for_import is False
    assert summary.tone == "error"


def test_phase33_replace_and_renumber_helpers_are_deterministic() -> None:
    entries = [
        TextSourceEntry("Hello world", "old-a.mp3", "A"),
        TextSourceEntry("HELLO again", "old-b.mp3", "B"),
    ]
    replaced, count = replace_entry_text(
        entries,
        find_text="hello",
        replacement="Hi",
        case_sensitive=False,
    )
    renamed = renumber_entry_filenames(replaced, prefix="Book chapter", start_index=7, extension=".wav")

    assert count == 2
    assert [entry.text for entry in renamed] == ["Hi world", "Hi again"]
    assert [entry.filename for entry in renamed] == ["Book-chapter-007.wav", "Book-chapter-008.wav"]


def test_phase33_workspace_exposes_preparation_panel_and_ready_state(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.set_manual_text("A clean sentence for generation.")
    qt_app.processEvents()

    assert isinstance(workspace.quality_panel, TextStudioQualityPanel)
    assert workspace.quality_summary.ready_for_import is True
    assert workspace.import_button.isEnabled() is True
    assert workspace.quality_panel.status_badge.text() == "Ready for queue"
    assert workspace.quality_panel.metric_labels["enabled"].text() == "1"


def test_phase33_duplicate_filenames_block_import_until_renumbered(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace._entries = [
        TextSourceEntry("First", "duplicate.mp3", "A"),
        TextSourceEntry("Second", "duplicate.mp3", "B"),
    ]
    workspace._render_entries()

    assert workspace.quality_summary.duplicate_filenames == 2
    assert workspace.import_button.isEnabled() is False

    workspace.renumber_filenames()

    assert workspace.quality_summary.duplicate_filenames == 0
    assert workspace.import_button.isEnabled() is True
    assert [entry.filename for entry in workspace._entries] == ["text-studio-001.mp3", "text-studio-002.mp3"]


def test_phase33_issue_annotation_does_not_reenter_table_change_handlers(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace._entries = [
        TextSourceEntry("First", "duplicate.mp3", "A"),
        TextSourceEntry("Second", "duplicate.mp3", "B"),
    ]
    workspace._render_entries()
    emitted: list[object] = []
    workspace.chunk_table.itemChanged.connect(emitted.append)

    workspace._annotate_quality_issues()

    assert emitted == []


def test_phase33_batch_cleanup_updates_entries_and_preserves_disabled_jobs(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace._entries = [
        TextSourceEntry(" First   job ", "one.mp3", "A"),
        TextSourceEntry(" First job ", "two.mp3", "B"),
        TextSourceEntry(" Third   job ", "three.mp3", "C"),
    ]
    workspace._render_entries()
    workspace.chunk_table.item(2, 0).setCheckState(Qt.Unchecked)

    workspace.normalize_all_text()
    workspace.remove_duplicate_text()

    assert [entry.text for entry in workspace._entries] == ["First job", "Third job"]
    assert workspace.chunk_table.item(1, 0).checkState() == Qt.Unchecked
    assert "Removed 1" in workspace.feedback.message_label.text()


def test_phase33_text_studio_has_direct_keyboard_navigation(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert window.view_text_studio_action.shortcut().toString() == "Ctrl+7"
    assert window.focus_workspace_region("text-studio") is True
    qt_app.processEvents()
    assert window.text_studio_dock.isVisible() is True
    assert window.text_studio.search.hasFocus() is True
