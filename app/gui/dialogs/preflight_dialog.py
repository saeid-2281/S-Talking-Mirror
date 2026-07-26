from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.preflight_state import PreflightFix
from app.models.preflight_state import PreflightState
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
        self.setWindowTitle("Preflight review")
        self.resize(920, 560)
        self._build()
        self.render()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Severity"))
        self.severity = QComboBox()
        self.severity.addItems(["All", "Errors", "Warnings"])
        self.severity.currentTextChanged.connect(self.render)
        filters.addWidget(self.severity)
        filters.addStretch()
        root.addLayout(filters)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Severity", "Row", "Filename", "Problem", "Suggested fix"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start generation")
        self.cancel_button = QPushButton("Cancel")
        self.export_button = QPushButton("Export report")
        self.copy_button = QPushButton("Copy summary")
        self.open_output_button = QPushButton("Open output folder")
        self.fix_button = QPushButton("Fix safe issues automatically")
        self.override_button = QPushButton("Override all eligible issues")
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.export_button.clicked.connect(lambda: self.export_report())
        self.copy_button.clicked.connect(self.copy_summary)
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.fix_button.clicked.connect(self.apply_fixes)
        self.override_button.clicked.connect(self.override_all)
        for button in [self.fix_button, self.override_button, self.export_button, self.copy_button, self.open_output_button]:
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button)
        root.addLayout(buttons)

    def render(self) -> None:
        self.summary.setText(
            f"{self.state.status}: {self.state.estimated_files:,} file(s), "
            f"{self.state.estimated_characters:,} characters, "
            f"{self.state.estimated_provider_requests:,} request(s), "
            f"ETA {format_duration(self.state.estimated_duration_seconds)}, "
            f"existing outputs {len(self.state.existing_outputs):,}, cost unavailable."
        )
        self.start_button.setText("Continue anyway" if self.state.status == "Ready with warnings" else "Start generation")
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
        QApplication.clipboard().setText(self.summary.text())

    def override_all(self) -> None:
        self.state.override_all_eligible("User override for this run")
        self.render()


class PreflightFixDialog(QDialog):
    def __init__(self, fixes: list[PreflightFix], parent=None) -> None:
        super().__init__(parent)
        self.fixes = fixes
        self.setWindowTitle("Preflight safe filename fixes")
        self.resize(820, 420)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        shown = min(len(self.fixes), 100)
        self.summary = QLabel(
            f"{len(self.fixes):,} filename fix(es) available. Showing {shown:,}. Source CSV and row text will not be modified."
        )
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = QTableWidget(shown, 4)
        self.table.setHorizontalHeaderLabels(["Row", "Original filename", "New filename", "Reason"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.table, 1)
        for row, fix in enumerate(self.fixes[:shown]):
            values = [fix.row, fix.original_filename, fix.new_filename, fix.reason]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        buttons = QHBoxLayout()
        export = QPushButton("Export full list")
        cancel = QPushButton("Cancel")
        apply = QPushButton("Apply fixes")
        export.clicked.connect(self.export_full_list)
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.accept)
        buttons.addWidget(export)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        root.addLayout(buttons)

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
