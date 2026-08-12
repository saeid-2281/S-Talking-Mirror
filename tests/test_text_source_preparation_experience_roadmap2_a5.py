from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel

from app.gui.dialogs.source_import_review_dialog import SourceImportReviewDialog
from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.models.project_source import SourceCollectionImportResult
from app.services.source_import_service import SourceImportService
from app.services.text_source_service import TextSourceService


def _result(tmp_path: Path) -> SourceCollectionImportResult:
    one = tmp_path / "one.csv"
    two = tmp_path / "two.csv"
    one.write_text("text,filename\nHej,one.mp3\n", encoding="utf-8")
    two.write_text("text,filename\nTak,two.mp3\n", encoding="utf-8")
    service = SourceImportService()
    return service.import_sources(service.create_sources([one, two]))


def _select_row(dialog: SourceImportReviewDialog, row: int) -> None:
    index = dialog.table.model().index(row, 0)
    dialog.table.selectionModel().select(
        index,
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )


def test_a5_text_studio_exposes_explicit_queue_handoff_status(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(
        TextSourceService(),
        session_path=tmp_path / "a5-text-studio.json",
    )
    workspace.set_manual_text("A clean sentence ready for generation.")
    qt_app.processEvents()

    assert workspace.import_button.isEnabled() is True
    assert "Queue handoff ready" in workspace.handoff_status.text()
    assert "Source Import Review" in workspace.handoff_status.text()
    assert "Preflight" in workspace.handoff_status.text()
    assert "generation" in workspace.handoff_status.text()


def test_a5_text_studio_blocked_handoff_is_visible(qt_app, tmp_path: Path) -> None:
    workspace = TextStudioWorkspace(
        TextSourceService(),
        session_path=tmp_path / "a5-blocked.json",
    )
    workspace._entries = [
        __import__("app.services.text_source_service", fromlist=["TextSourceEntry"]).TextSourceEntry(
            "First",
            "same.mp3",
            "A",
        ),
        __import__("app.services.text_source_service", fromlist=["TextSourceEntry"]).TextSourceEntry(
            "Second",
            "same.mp3",
            "B",
        ),
    ]
    workspace._render_entries()
    qt_app.processEvents()

    assert workspace.import_button.isEnabled() is False
    assert "Queue handoff blocked" in workspace.handoff_status.text()


def test_a5_source_review_selected_import_requires_valid_selection(qt_app, tmp_path: Path) -> None:
    dialog = SourceImportReviewDialog(
        _result(tmp_path),
        current_queue_jobs=12,
        current_source_count=1,
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.import_all_button.isEnabled() is True
    assert dialog.import_selected_button.isEnabled() is False
    assert "Select at least one valid source" in dialog.import_selected_button.toolTip()

    dialog.import_selected()

    assert dialog.result() == 0
    dialog.close()


def test_a5_source_review_selection_enables_selected_handoff(qt_app, tmp_path: Path) -> None:
    dialog = SourceImportReviewDialog(
        _result(tmp_path),
        current_queue_jobs=12,
        current_source_count=1,
    )
    dialog.show()
    _select_row(dialog, 0)
    qt_app.processEvents()

    assert dialog.import_selected_button.isEnabled() is True
    assert "1 job(s)" in dialog.import_selected_button.toolTip()
    assert len(dialog._selected_importable_results()) == 1
    assert dialog._selected_importable_job_count() == 1
    dialog.close()


def test_a5_queue_handoff_card_explains_rebuild_and_authority_boundary(qt_app, tmp_path: Path) -> None:
    dialog = SourceImportReviewDialog(
        _result(tmp_path),
        current_queue_jobs=8,
        current_source_count=2,
    )
    dialog.show()
    qt_app.processEvents()

    detail = dialog.handoff_card.detail_label.text()
    assert "Current queue has 8 job(s)" in detail
    assert "will be rebuilt" in detail
    assert "Preflight is NOT run automatically" in detail
    assert "generation is NOT started" in detail
    dialog.close()


def test_a5_empty_queue_handoff_text_is_explicit(qt_app, tmp_path: Path) -> None:
    dialog = SourceImportReviewDialog(_result(tmp_path), current_queue_jobs=0)
    dialog.show()
    qt_app.processEvents()

    assert "Current queue is empty" in dialog.handoff_card.detail_label.text()
    dialog.close()


def test_a5_import_all_valid_still_preserves_historical_behavior(qt_app, tmp_path: Path) -> None:
    dialog = SourceImportReviewDialog(_result(tmp_path))
    dialog.show()
    qt_app.processEvents()

    dialog.import_all_valid()

    assert dialog.selected_mode == "all"
    assert dialog.result() != 0


def test_a5_main_passes_real_queue_context_to_source_review() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def import_source_paths", 1)[1].split("def selected_source_rows", 1)[0]

    assert "current_queue_jobs=len(list(self.generation_controller.generation_jobs()))" in method
    assert "current_source_count=len(self.project_sources)" in method
    assert "if not importable:" in method
    assert "Queue unchanged" in method


def test_a5_main_post_import_status_keeps_preflight_and_generation_explicit() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def import_source_paths", 1)[1].split("def selected_source_rows", 1)[0]

    assert "self.invalidate_preflight()" in method
    assert "Preflight has NOT run" in method
    assert "generation has NOT started" in method
    assert "self.dry_run(" not in method
    assert "self.start(" not in method


def test_a5_onboarding_project_sources_handoff_opens_text_studio() -> None:
    from app.services.first_run_onboarding_service import FirstRunOnboardingService

    step = next(
        step
        for step in FirstRunOnboardingService.steps()
        if step.step_id == "project_sources"
    )

    assert step.action_id == "text_source_preparation"
    assert step.action_label == "Open Text & Source Preparation"
    assert "Source Import Review" in step.description


def test_a5_main_onboarding_action_map_wires_text_source_preparation() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def open_first_run_onboarding", 1)[1].split(
        "def open_quick_setup",
        1,
    )[0]

    assert "'text_source_preparation':self.open_text_studio" in method


def test_a5_onboarding_still_has_six_steps() -> None:
    from app.services.first_run_onboarding_service import FirstRunOnboardingService

    assert len(FirstRunOnboardingService.steps()) == 6
    assert [step.step_id for step in FirstRunOnboardingService.steps()] == [
        "workspace_orientation",
        "provider_readiness",
        "voice_model_choice",
        "project_sources",
        "preflight_approval",
        "generation_output",
    ]


def test_a5_source_review_does_not_run_preflight_generation_or_routing() -> None:
    source = Path("app/gui/dialogs/source_import_review_dialog.py").read_text(
        encoding="utf-8"
    )

    for forbidden in (
        ".dry_run(",
        ".run_preflight(",
        ".start(",
        "smart_provider_routing",
        "generation_controller",
    ):
        assert forbidden not in source


def test_a5_source_review_preserves_existing_public_actions() -> None:
    source = Path("app/gui/dialogs/source_import_review_dialog.py").read_text(
        encoding="utf-8"
    )

    for token in (
        'self.import_all_button = QPushButton("Import all valid")',
        'self.import_selected_button = QPushButton("Import selected")',
        "def importable_results",
        "def toggle_selected",
        "def remove_selected",
        "def reconfigure_selected",
        "def export_diagnostics",
    ):
        assert token in source


def test_a5_database_schema_23_is_preserved(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "a5-schema.db")
    database.initialize()

    assert database.expected_schema_version == 23
    assert database.applied_schema_versions()[-1] == 23


def test_a5_files_have_single_final_newline() -> None:
    paths = (
        Path("app/gui/widgets/text_studio_workspace.py"),
        Path("app/gui/dialogs/source_import_review_dialog.py"),
        Path("app/gui/main.py"),
        Path("app/services/first_run_onboarding_service.py"),
        Path("docs/TEXT_SOURCE_PREPARATION_EXPERIENCE_ROADMAP2_A5.md"),
        Path(__file__),
    )

    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
