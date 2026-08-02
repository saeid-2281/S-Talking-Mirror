from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton, QScrollArea

from app.gui.dialogs.interface_preferences_dialog import InterfacePreferencesDialog
from app.gui.dialogs.new_project_dialog import NewProjectDialog
from app.gui.dialogs.preflight_dialog import PreflightDialog, PreflightFixDialog
from app.gui.dialogs.quick_setup_dialog import QuickSetupDialog
from app.gui.dialogs.source_import_review_dialog import SourceImportReviewDialog
from app.gui.interface_preferences import InterfacePreferences
from app.gui.widgets.dialog_workspace import DialogSection, DialogWorkspace
from app.models import AppSettings
from app.models.preflight_state import PreflightFix, PreflightIssue, PreflightState
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.source_import_service import SourceImportService


def test_phase28_dialog_workspace_keeps_footer_outside_scroll_area(qt_app) -> None:
    workspace = DialogWorkspace("Settings", "A readable settings workspace")
    workspace.add_body_widget(DialogSection("General", "Scrollable content"))
    workspace.show()
    qt_app.processEvents()

    assert isinstance(workspace.body_scroll, QScrollArea)
    assert workspace.body_scroll.widgetResizable() is True
    assert workspace.footer.objectName() == "dialogStickyFooter"
    assert workspace.footer.parent() is workspace
    assert not workspace.body_scroll.isAncestorOf(workspace.footer)
    workspace.close()


def test_phase28_interface_preferences_uses_scroll_body_and_sticky_actions(qt_app) -> None:
    dialog = InterfacePreferencesDialog(InterfacePreferences.defaults())
    dialog.resize(540, 440)
    dialog.show()
    qt_app.processEvents()

    assert dialog.workspace.body_scroll.isVisible() is True
    assert dialog.workspace.footer.isVisible() is True
    assert dialog.workspace.body_scroll.isAncestorOf(dialog.preview)
    assert not dialog.workspace.body_scroll.isAncestorOf(dialog.button_box)
    assert dialog.minimumWidth() <= 540
    dialog.close()


def test_phase28_quick_setup_exposes_progress_rail_and_pinned_navigation(qt_app) -> None:
    dialog = QuickSetupDialog(ProviderCatalogService(), AppSettings(provider="mock"))
    dialog.show()
    qt_app.processEvents()

    assert dialog.step_rail.objectName() == "setupStepRail"
    assert len(dialog.step_labels) == dialog.stack.count() == 6
    assert dialog.progress_bar.value() == 1
    assert dialog.step_labels[0].property("active") is True
    assert not dialog.workspace.body_scroll.isAncestorOf(dialog.next)

    for _ in range(dialog.stack.count() - 1):
        dialog.next_page()
    assert dialog.finish.isVisible() is True
    assert dialog.next.isVisible() is False
    assert dialog.progress_bar.value() == dialog.stack.count()
    dialog.close()


def test_phase28_new_project_primary_action_remains_visible_and_validated(qt_app, tmp_path: Path) -> None:
    dialog = NewProjectDialog(output_dir=tmp_path)
    dialog.resize(540, 410)
    dialog.show()
    qt_app.processEvents()

    assert dialog.workspace.footer.isVisible() is True
    assert dialog.create_button.isVisible() is True
    assert dialog.create_button.isEnabled() is True
    dialog.name.clear()
    assert dialog.create_button.isEnabled() is False
    dialog.name.setText("Audio project")
    assert dialog.create_button.isEnabled() is True
    assert dialog.values()[0] == "Audio project"
    dialog.close()


def test_phase28_preflight_moves_secondary_tools_into_scroll_body(qt_app, tmp_path: Path) -> None:
    state = PreflightState(
        total_jobs=2,
        warnings=1,
        estimated_files=2,
        estimated_characters=120,
        estimated_provider_requests=2,
        estimated_duration_seconds=4.0,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        issues=[
            PreflightIssue(
                severity="warning",
                row=1,
                filename="one.mp3",
                message="Existing output",
                suggested_action="Review output policy",
            )
        ],
    )
    dialog = PreflightDialog(
        state,
        export_report=lambda: tmp_path / "report.json",
        open_output_folder=lambda: None,
        apply_fixes=lambda: None,
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.table.objectName() == "preflightIssuesTable"
    assert dialog.workspace.body_scroll.isAncestorOf(dialog.fix_button)
    assert dialog.workspace.body_scroll.isAncestorOf(dialog.export_button)
    assert not dialog.workspace.body_scroll.isAncestorOf(dialog.start_button)
    assert dialog.start_button.isVisible() is True
    assert dialog.cancel_button.isVisible() is True
    dialog.close()


def test_phase28_preflight_fix_dialog_keeps_apply_action_pinned(qt_app) -> None:
    dialog = PreflightFixDialog(
        [PreflightFix(row=1, original_filename="bad:name.mp3", new_filename="bad-name.mp3", reason="Invalid character")]
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.table.objectName() == "preflightFixesTable"
    assert dialog.workspace.footer.isVisible() is True
    primary = dialog.workspace.footer.findChild(QPushButton, "dialogPrimaryAction")
    assert primary is not None
    assert primary.text() == "Apply fixes"
    assert not dialog.workspace.body_scroll.isAncestorOf(primary)
    assert dialog.table.rowCount() == 1
    dialog.close()


def test_phase28_source_import_review_keeps_import_actions_pinned(qt_app, tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("filename,text\none.mp3,Hej\n", encoding="utf-8")
    service = SourceImportService()
    result = service.import_sources(service.create_sources([source]))
    dialog = SourceImportReviewDialog(result)
    dialog.resize(760, 520)
    dialog.show()
    qt_app.processEvents()

    assert dialog.table.objectName() == "sourceImportTable"
    assert dialog.workspace.body_scroll.isAncestorOf(dialog.tool_buttons[0])
    assert not dialog.workspace.body_scroll.isAncestorOf(dialog.import_selected_button)
    assert dialog.import_selected_button.isVisible() is True
    assert dialog.import_all_button.isVisible() is True
    assert dialog.cancel_button.isVisible() is True
    dialog.close()
