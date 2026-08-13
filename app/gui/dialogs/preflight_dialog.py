from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.icons import action_icon
from app.gui.widgets.batch_plan_summary import BatchPlanSummary
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.preflight_state import PreflightFix, PreflightState
from app.services.monitor_formatting import format_duration


class PreflightDialog(QDialog):
    def __init__(
        self,
        state: PreflightState,
        *,
        export_report: Callable[[], Path],
        open_output_folder: Callable[[], None],
        apply_fixes: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.export_report = export_report
        self.open_output_folder = open_output_folder
        self.apply_fixes = apply_fixes
        self.setObjectName("preflightDialog")
        self.setWindowTitle("Preflight review")
        self.resize(980, 680)
        self.setMinimumSize(700, 480)
        self._build()
        self.render()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.workspace = DialogWorkspace(
            "Preflight review",
            "Review blocking errors, warnings and safe fixes. Preflight review never starts generation.",
            icon_name="generation.preflight",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.summary_card = DialogStatusCard("Checking generation readiness", "", tone="info")
        self.summary_card.setObjectName("preflightSummaryCard")
        self.summary = self.summary_card.detail_label
        self.workspace.add_body_widget(self.summary_card)

        plan_section = DialogSection(
            "Batch plan and risk preview",
            "Compare the base run with retry-reserve scenarios before committing provider quota or budget.",
        )
        self.plan_summary = BatchPlanSummary()
        plan_section.add_widget(self.plan_summary)
        self.workspace.add_body_widget(plan_section)

        issue_section = DialogSection(
            "Issues and recommendations",
            "Filter by severity, inspect the affected row, and review the suggested action before overriding anything.",
        )
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("Severity"))
        self.severity = QComboBox()
        self.severity.setObjectName("preflightSeverityFilter")
        self.severity.addItems(["All", "Errors", "Warnings"])
        self.severity.currentTextChanged.connect(self.render)
        filter_row.addWidget(self.severity)
        filter_row.addStretch(1)
        issue_section.add_layout(filter_row)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("preflightIssuesTable")
        self.table.setHorizontalHeaderLabels(["Severity", "Row", "Filename", "Problem", "Suggested fix"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(260)
        issue_section.add_widget(self.table, 1)
        self.workspace.add_body_widget(issue_section, 1)

        tools_section = DialogSection(
            "Review tools",
            "Secondary actions stay inside the scrollable body so the primary Start and Cancel controls remain visible at every window height.",
        )
        tools = QGridLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setHorizontalSpacing(8)
        tools.setVerticalSpacing(8)
        self.fix_button = QPushButton("Fix safe issues automatically")
        self.override_button = QPushButton("Override all eligible issues")
        self.export_button = QPushButton("Export report")
        self.copy_button = QPushButton("Copy summary")
        self.open_output_button = QPushButton("Open output folder")
        self.fix_button.setIcon(action_icon("general.success"))
        self.override_button.setIcon(action_icon("general.warning"))
        self.export_button.setIcon(action_icon("report"))
        self.copy_button.setIcon(action_icon("general.copy"))
        self.open_output_button.setIcon(action_icon("project.output_folder"))
        self.fix_button.clicked.connect(self.apply_fixes)
        self.override_button.clicked.connect(self.override_all)
        self.export_button.clicked.connect(lambda: self.export_report())
        self.copy_button.clicked.connect(self.copy_summary)
        self.open_output_button.clicked.connect(self.open_output_folder)
        for index, button in enumerate(
            [
                self.fix_button,
                self.override_button,
                self.export_button,
                self.copy_button,
                self.open_output_button,
            ]
        ):
            button.setObjectName("preflightToolAction")
            button.setMinimumHeight(34)
            tools.addWidget(button, index // 2, index % 2)
        tools.setColumnStretch(0, 1)
        tools.setColumnStretch(1, 1)
        tools_section.add_layout(tools)
        self.workspace.add_body_widget(tools_section)

        self.cancel_button = QPushButton("Close")
        self.start_button = QPushButton("Review complete")
        self.start_button.setObjectName("dialogPrimaryAction")
        self.start_button.setIcon(action_icon("generation.start"))
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.workspace.add_footer_stretch()
        self.workspace.add_footer_widget(self.cancel_button)
        self.workspace.add_footer_widget(self.start_button)

    def render(self) -> None:
        cost_text = "Cost unavailable"
        if self.state.generation_plan is not None and self.state.generation_plan.cost_available:
            cost_text = f"{self.state.generation_plan.currency} {self.state.generation_plan.estimated_cost:,.4f}"
        detail = (
            f"{self.state.estimated_files:,} file(s) · "
            f"{self.state.estimated_characters:,} characters · "
            f"{self.state.estimated_provider_requests:,} request(s) · "
            f"ETA {format_duration(self.state.estimated_duration_seconds)} · "
            f"{len(self.state.existing_outputs):,} existing output(s) · {cost_text}"
        )
        tone = "success" if self.state.status == "Ready" else "warning"
        if not self.state.can_start:
            tone = "error"
        self.summary_card.update_status(self.state.status, detail, tone=tone)
        self.plan_summary.set_plan(self.state.generation_plan)
        self.start_button.setText(
            "Warnings reviewed" if self.state.status == "Ready with warnings" else "Review complete"
        )
        self.start_button.setToolTip(
            "Close this Preflight review. Generation is started separately from the explicit launch control."
        )
        selected = self.severity.currentText()
        issues = self.state.issues
        if selected == "Errors":
            issues = [issue for issue in issues if issue.severity in {"hard_error", "overridable_error", "error"}]
        elif selected == "Warnings":
            issues = [issue for issue in issues if issue.severity == "warning"]
        self.table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            severity = f"{issue.severity}{' (overridden)' if issue.overridden else ''}"
            values = [severity, issue.row or "—", issue.filename, issue.message, issue.suggested_action]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column in {0, 1}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self.start_button.setEnabled(self.state.can_start)
        self.override_button.setEnabled(any(issue.overridable and not issue.overridden for issue in self.state.issues))

    def copy_summary(self) -> None:
        QApplication.clipboard().setText(
            f"{self.summary_card.title_label.text()}: {self.summary.text()}"
        )

    def override_all(self) -> None:
        self.state.override_all_eligible("User override for this run")
        self.render()


class PreflightFixDialog(QDialog):
    def __init__(self, fixes: list[PreflightFix], parent=None) -> None:
        super().__init__(parent)
        self.fixes = fixes
        self.setObjectName("preflightFixDialog")
        self.setWindowTitle("Preflight safe filename fixes")
        self.resize(860, 540)
        self.setMinimumSize(620, 420)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Safe filename fixes",
            "Review generated filename corrections before applying them. Source CSV data and row text are never modified.",
            icon_name="general.success",
            parent=self,
        )
        root.addWidget(self.workspace)
        shown = min(len(self.fixes), 100)
        section = DialogSection(
            "Fix preview",
            f"{len(self.fixes):,} fix(es) available · Showing {shown:,}",
        )
        self.summary = section.subtitle_label
        self.table = QTableWidget(shown, 4)
        self.table.setObjectName("preflightFixesTable")
        self.table.setHorizontalHeaderLabels(["Row", "Original filename", "New filename", "Reason"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setMinimumHeight(260)
        section.add_widget(self.table, 1)
        self.workspace.add_body_widget(section, 1)
        for row, fix in enumerate(self.fixes[:shown]):
            values = [fix.row, fix.original_filename, fix.new_filename, fix.reason]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        export = QPushButton("Export full list")
        cancel = QPushButton("Cancel")
        apply = QPushButton("Apply fixes")
        apply.setObjectName("dialogPrimaryAction")
        export.clicked.connect(self.export_full_list)
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.accept)
        self.workspace.add_footer_widget(export)
        self.workspace.add_footer_stretch()
        self.workspace.add_footer_widget(cancel)
        self.workspace.add_footer_widget(apply)

    def export_full_list(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export filename fixes", "preflight-filename-fixes.csv", "CSV (*.csv)")
        if not path:
            return
        import csv

        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["row", "original_filename", "new_filename", "reason"])
            writer.writeheader()
            for fix in self.fixes:
                writer.writerow(fix.__dict__)
