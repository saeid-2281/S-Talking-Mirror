from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from app.gui.widgets.text_batch_preparation import TextBatchPreparationPanel
from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.services.text_batch_preparation_service import TextBatchPreparationService
from app.services.text_source_service import TextSourceEntry, TextSourceService
from app.services.text_studio_quality import analyze_text_studio_entries


def _service() -> TextBatchPreparationService:
    return TextBatchPreparationService(TextSourceService())


def _workspace(tmp_path: Path) -> TextStudioWorkspace:
    return TextStudioWorkspace(TextSourceService(), session_path=tmp_path / "phase91-session.json")


def test_phase91_empty_snapshot_points_to_source_input() -> None:
    snapshot = _service().evaluate([])

    assert snapshot.next_action == "add-source"
    assert snapshot.next_label == "Add or paste source"
    assert snapshot.enabled_jobs == 0
    assert snapshot.ready_for_queue is False
    assert [stage.code for stage in snapshot.stages] == [
        "input",
        "structure",
        "quality",
        "batch",
        "queue",
    ]


def test_phase91_snapshot_prioritizes_safe_non_destructive_fixes() -> None:
    entries = [
        TextSourceEntry(" First   row ", "same.mp3", "A"),
        TextSourceEntry("Second row", "same.mp3", "B"),
    ]
    quality = analyze_text_studio_entries(entries, max_characters=100)

    snapshot = _service().evaluate(
        entries,
        enabled=[True, True],
        source_count=1,
        max_characters=100,
        quality=quality,
    )

    assert snapshot.next_action == "safe-prepare"
    assert snapshot.safe_fix_count >= 3
    assert snapshot.blocking_issues == 2
    assert snapshot.tone == "error"


def test_phase91_safe_prepare_normalizes_and_splits_enabled_rows() -> None:
    entries = [
        TextSourceEntry("  One   sentence.   Two sentence.   Three sentence.  ", "speech.mp3", "Manual"),
    ]

    result = _service().safe_prepare(entries, enabled=[True], max_characters=22)

    assert result.normalized_jobs == 1
    assert result.split_jobs == 1
    assert result.generated_jobs >= 1
    assert len(result.entries) > 1
    assert all(len(entry.text) <= 22 for entry in result.entries)
    assert [entry.filename for entry in result.entries] == [
        f"speech-part-{index:03d}.mp3" for index in range(1, len(result.entries) + 1)
    ]
    assert all(result.enabled)


def test_phase91_safe_prepare_repairs_invalid_and_duplicate_enabled_filenames() -> None:
    entries = [
        TextSourceEntry("First", "bad/name?.mp3", "A"),
        TextSourceEntry("Second", "name-.mp3", "B"),
        TextSourceEntry("Third", "name-.mp3", "C"),
    ]

    result = _service().safe_prepare(entries, enabled=[True, True, True], max_characters=1200)
    names = [entry.filename for entry in result.entries]

    assert result.repaired_filenames >= 2
    assert len({name.casefold() for name in names}) == 3
    assert all("/" not in name and "?" not in name for name in names)


def test_phase91_safe_prepare_preserves_disabled_rows_exactly() -> None:
    disabled = TextSourceEntry("  Disabled   spacing  ", "bad/name?.mp3", "Disabled")
    enabled = TextSourceEntry("  Enabled   spacing  ", "good.mp3", "Enabled")

    result = _service().safe_prepare(
        [disabled, enabled],
        enabled=[False, True],
        max_characters=1200,
    )

    assert result.entries[0] == disabled
    assert result.enabled == (False, True)
    assert result.entries[1].text == "Enabled spacing"


def test_phase91_duplicate_text_remains_explicit_manual_decision() -> None:
    entries = [
        TextSourceEntry("Same text", "one.mp3", "A"),
        TextSourceEntry("Same   text", "two.mp3", "B"),
    ]
    result = _service().safe_prepare(entries, enabled=[True, True], max_characters=1200)
    snapshot = _service().evaluate(
        list(result.entries),
        enabled=list(result.enabled),
        source_count=1,
        max_characters=1200,
    )

    assert len(result.entries) == 2
    assert snapshot.duplicate_texts == 2
    assert snapshot.blocking_issues == 0
    assert snapshot.ready_for_queue is True
    assert snapshot.next_action == "review-duplicates"


def test_phase91_clean_batch_points_to_existing_import_review() -> None:
    entries = [TextSourceEntry("Clean text", "clean.mp3", "Manual")]
    snapshot = _service().evaluate(entries, enabled=[True], source_count=1, max_characters=1200)

    assert snapshot.ready_for_queue is True
    assert snapshot.next_action == "queue"
    assert snapshot.next_label == "Review & add to queue"
    assert snapshot.stages[-1].status == "pass"


def test_phase91_workspace_exposes_preparation_flow(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.set_manual_text("A clean sentence for generation.")
    qt_app.processEvents()

    assert isinstance(workspace.preparation_panel, TextBatchPreparationPanel)
    assert workspace.preparation_snapshot.next_action == "queue"
    assert workspace.preparation_panel.primary_action.text() == "Review & add to queue"
    assert workspace.import_button.text() == "Review & add to queue"
    assert workspace.preparation_panel.stage_labels["queue"].property("status") == "pass"


def test_phase91_workspace_safe_prepare_fixes_enabled_rows_and_preserves_disabled(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace._entries = [
        TextSourceEntry(" First   row ", "same.mp3", "A"),
        TextSourceEntry(" Second   row ", "same.mp3", "B"),
        TextSourceEntry(" Disabled   row ", "bad/name?.mp3", "C"),
    ]
    workspace._render_entries()
    workspace.chunk_table.item(2, 0).setCheckState(Qt.Unchecked)
    qt_app.processEvents()

    workspace.safe_prepare_enabled()

    assert workspace._entries[0].text == "First row"
    assert workspace._entries[1].text == "Second row"
    assert workspace._entries[2].text == " Disabled   row "
    assert workspace._entries[2].filename == "bad/name?.mp3"
    assert workspace.chunk_table.item(2, 0).checkState() == Qt.Unchecked
    assert workspace.quality_summary.blocking_issues == 0


def test_phase91_workspace_review_duplicates_filters_issue_rows(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace._entries = [
        TextSourceEntry("Same text", "one.mp3", "A"),
        TextSourceEntry("Same text", "two.mp3", "B"),
        TextSourceEntry("Unique", "three.mp3", "C"),
    ]
    workspace._render_entries()

    workspace._handle_preparation_action("review-duplicates")
    qt_app.processEvents()

    assert workspace.quality_panel.issues_only.isChecked() is True
    assert workspace.chunk_table.isRowHidden(0) is False
    assert workspace.chunk_table.isRowHidden(1) is False
    assert workspace.chunk_table.isRowHidden(2) is True
    assert "manual action" in workspace.feedback.message_label.text()


def test_phase91_workspace_queue_action_reuses_import_signal(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.set_manual_text("Ready text.")
    qt_app.processEvents()
    captured: list[tuple[object, str]] = []
    workspace.import_requested.connect(lambda entries, label: captured.append((entries, label)))

    workspace._handle_preparation_action("queue")

    assert len(captured) == 1
    entries, label = captured[0]
    assert len(entries) == 1
    assert label == "Text Studio"


def test_phase91_source_action_focuses_manual_input(qt_app, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.show()
    qt_app.processEvents()

    workspace._handle_preparation_action("add-source")
    qt_app.processEvents()

    assert workspace.manual_text.hasFocus() is True


def test_phase91_theme_and_safety_documentation_contract() -> None:
    theme = Path("app/gui/theme.py").read_text(encoding="utf-8")
    docs = Path("docs/TEXT_SOURCE_BATCH_PREPARATION_PHASE91.md").read_text(encoding="utf-8")

    assert "textBatchPreparationPanel" in theme
    assert 'textBatchPreparationStage[status="block"]' in theme
    assert "does not delete duplicate text" in docs
    assert "Source Import Review" in docs
    assert "Preflight" in docs
