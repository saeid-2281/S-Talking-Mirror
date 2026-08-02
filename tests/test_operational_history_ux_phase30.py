from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFrame, QGridLayout

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.gui.dialogs.generation_history_dialog import GenerationHistoryDialog
from app.gui.dialogs.report_dialog import ReportDialog
from app.gui.widgets.activity_timeline import ActivityEventCard, ActivityTimelineWidget
from app.gui.widgets.application_shell import ActivityCenter
from app.gui.widgets.dialog_workspace import DialogWorkspace
from app.models import GenerationReport
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_history_service import GenerationHistoryService


def _session(session_id: str, *, result: str = "completed", severity: str = "none") -> BatchSessionRecord:
    return BatchSessionRecord(
        session_id=session_id,
        project_id=None,
        scope="entire_queue",
        provider="mock",
        model="mock-v1",
        voice="da-DK",
        total_jobs=10,
        completed_jobs=9 if result == "completed" else 4,
        failed_jobs=1 if result == "completed" else 6,
        skipped_jobs=0,
        character_count=1000,
        report_path="reports/run/report.html",
        output_path="output",
        result=result,
        started_at="2026-08-01T10:00:00+00:00",
        finished_at="2026-08-01T10:01:00+00:00",
        elapsed_seconds=60.0,
        files_per_minute=10.0,
        characters_per_minute=1000.0,
        health_score=95.0 if severity == "none" else 55.0,
        regression_severity=severity,
        alert_state="open" if severity != "none" else "none",
    )


def test_phase30_activity_timeline_uses_professional_cards(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    container.product_activity_service.activity("generation", "Batch started", "10 jobs entered the active queue")
    container.product_activity_service.activity("report", "Report created", "HTML and CSV artifacts are ready")
    widget = ActivityTimelineWidget(container.activity_timeline_service)
    widget.show()
    qt_app.processEvents()

    assert widget.header.objectName() == "activityTimelineHeader"
    assert widget.filter_bar.objectName() == "activityTimelineFilterBar"
    assert widget.list_widget.count() == 2
    assert isinstance(widget.list_widget.itemWidget(widget.list_widget.item(0)), ActivityEventCard)
    assert widget.count_badge.text() == "2 events"
    assert widget.copy_visible_button.isEnabled() is True
    widget.close()


def test_phase30_activity_timeline_filters_and_details(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    container.product_activity_service.activity("provider", "Provider ready", "Voice catalog refreshed", metadata={"voices": 12})
    container.product_activity_service.activity("generation", "Batch completed", "All files generated")
    widget = ActivityTimelineWidget(container.activity_timeline_service)
    widget.show()
    qt_app.processEvents()

    widget.category.setCurrentText("Provider")
    assert widget.list_widget.count() == 1
    widget.list_widget.setCurrentRow(0)
    widget.update_details()
    assert "Provider ready" in widget.details.toPlainText()
    assert '"voices": 12' in widget.details.toPlainText()
    widget.search.setText("missing")
    assert widget.content_stack.currentIndex() == 1
    widget.clear_filters()
    assert widget.list_widget.count() == 2
    widget.close()


def test_phase30_generation_history_has_sticky_workspace_and_action_grid(qt_app, tmp_path: Path) -> None:
    database = Database(tmp_path / "history.db")
    database.initialize()
    repository = ProductEventRepository(database)
    repository.add_batch_session(_session("session-a"))
    dialog = GenerationHistoryDialog(
        GenerationHistoryService(repository),
        project_name="Phase 30",
        export_dir=tmp_path / "exports",
        open_path=lambda _path: None,
        copy_path=lambda _path: None,
    )
    dialog.show()
    qt_app.processEvents()

    assert isinstance(dialog.workspace, DialogWorkspace)
    assert dialog.table.objectName() == "generationHistoryTable"
    assert dialog.table.rowCount() == 1
    actions_section = dialog.findChild(QFrame, "historyActionsSection")
    assert actions_section is not None
    assert isinstance(actions_section.content_layout.itemAt(0).layout(), QGridLayout)
    assert dialog.workspace.footer.isVisible() is True
    dialog.close()


def test_phase30_generation_history_summary_surfaces_operational_health(qt_app, tmp_path: Path) -> None:
    database = Database(tmp_path / "summary.db")
    database.initialize()
    repository = ProductEventRepository(database)
    repository.add_batch_session(_session("healthy"))
    repository.add_batch_session(_session("warning", severity="warning"))
    dialog = GenerationHistoryDialog(
        GenerationHistoryService(repository),
        project_name="Phase 30",
        export_dir=tmp_path / "exports",
        open_path=lambda _path: None,
        copy_path=lambda _path: None,
    )

    assert dialog.metric_values["sessions"].text() == "2"
    assert dialog.metric_values["regressions"].text() == "1"
    assert dialog.metric_values["alerts"].text() == "1"
    assert "review" in dialog.summary_card.title_label.text().casefold()
    dialog.close()


def test_phase30_report_dialog_exposes_paths_metrics_and_actions(qt_app, tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    report = GenerationReport(
        report_dir=report_dir,
        summary={
            "total_files": 10,
            "completed": 8,
            "skipped": 1,
            "failed": 1,
            "project_name": "Phase 30",
            "provider": "mock",
            "model": "mock-v1",
            "voice": "da-DK",
            "output_dir": str(tmp_path / "output"),
        },
    )
    opened: list[Path] = []
    copied: list[Path] = []
    diagnostics: list[Path] = []
    dialog = ReportDialog(
        report,
        open_report=opened.append,
        open_folder=opened.append,
        copy_path=copied.append,
        export_diagnostics=diagnostics.append,
    )
    dialog.show()
    qt_app.processEvents()

    assert isinstance(dialog.workspace, DialogWorkspace)
    assert dialog.metric_values["total"].text() == "10"
    assert dialog.metric_values["failed"].text() == "1"
    assert str(report_dir) in dialog.path_label.text()
    dialog.open_report_button.click()
    dialog.copy_path_button.click()
    dialog.export_diagnostics_button.click()
    assert opened == [report.report_html]
    assert copied == [report_dir]
    assert diagnostics == [report_dir]
    dialog.close()


def test_phase30_report_dialog_uses_success_state_for_clean_run(qt_app, tmp_path: Path) -> None:
    report = GenerationReport(
        report_dir=tmp_path,
        summary={"total_files": 3, "completed": 3, "skipped": 0, "failed": 0},
    )
    dialog = ReportDialog(
        report,
        open_report=lambda _path: None,
        open_folder=lambda _path: None,
        copy_path=lambda _path: None,
        export_diagnostics=lambda _path: None,
    )
    assert dialog.status_card.property("tone") == "success"
    assert "successfully" in dialog.status_card.title_label.text().casefold()
    dialog.close()


def test_phase30_activity_center_expands_for_operational_timeline(qt_app) -> None:
    center = ActivityCenter()
    assert center.maximumHeight() <= 34
    center.set_expanded(True)
    assert center.maximumHeight() >= 300
    assert center.minimumHeight() >= 96
    center.close()
