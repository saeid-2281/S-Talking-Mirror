from __future__ import annotations

import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.crash_recovery_service import CrashRecoveryService


class CrashRecoveryDialog(QDialog):
    """Review privacy-safe crash evidence and create a verified support bundle."""

    def __init__(
        self,
        service: CrashRecoveryService,
        parent: QWidget | None = None,
        *,
        open_path=None,
        copy_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.copy_path = copy_path
        self.current_snapshot = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("crashRecoveryDialog")
        self.setWindowTitle("Crash recovery and production diagnostics")
        self.resize(1180, 780)
        self.setMinimumSize(880, 620)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Crash recovery and production diagnostics",
            "Review structured crash evidence, verify recovery artifacts and export a privacy-safe diagnostics bundle without exposing project text or credentials.",
            icon_name="warning",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting crash evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        gate_section = DialogSection(
            "Recovery gates",
            "Integrity and database failures block support export trust. Warnings identify unclean shutdowns or malformed resumable state.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("crashRecoveryGateTable")
        self.gate_table.setHorizontalHeaderLabels(["Status", "Gate", "Severity", "Evidence", "Action"])
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gate_section.add_widget(self.gate_table)
        self.workspace.add_body_widget(gate_section)

        report_section = DialogSection(
            "Crash history",
            "Reports contain frame metadata only—never source-code lines, local variables, project text, API profiles, databases or generated audio.",
        )
        self.report_table = QTableWidget(0, 8)
        self.report_table.setObjectName("crashRecoveryReportTable")
        self.report_table.setHorizontalHeaderLabels(
            ["State", "Time", "Source", "Severity", "Exception", "Summary", "Integrity", "Report ID"]
        )
        self.report_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.report_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.report_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.report_table.itemSelectionChanged.connect(self.show_selected_report)
        report_section.add_widget(self.report_table)
        self.workspace.add_body_widget(report_section)

        detail_section = DialogSection(
            "Selected report",
            "The detail view is integrity verified and redacted before display.",
        )
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("crashRecoveryDetail")
        self.detail.setReadOnly(True)
        self.detail.setMaximumBlockCount(5000)
        detail_section.add_widget(self.detail)
        self.workspace.add_body_widget(detail_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        buttons = (
            ("Refresh", self.refresh, "general.refresh", False),
            ("Acknowledge selected", self.acknowledge_selected, "general.success", False),
            ("Export diagnostics bundle", self.export_bundle, "save", True),
            ("Copy safe-mode command", self.copy_safe_mode_command, "general.copy", False),
            ("Open crash folder", self.open_crash_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in buttons:
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.clicked.connect(handler)
            if primary:
                button.setObjectName("dialogPrimaryAction")
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def refresh(self) -> None:
        snapshot = self.service.snapshot()
        self.current_snapshot = snapshot
        tone = "success" if snapshot.status == "healthy" else "warning" if snapshot.status == "attention" else "error"
        self.summary.update_status(
            snapshot.summary,
            (
                f"{snapshot.crash_count} report(s) · {snapshot.unacknowledged_count} unacknowledged · "
                f"{snapshot.integrity_failure_count} integrity issue(s) · safe mode {'active' if snapshot.safe_mode else 'available'}"
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status.title(),
                gate.label,
                gate.severity.title(),
                gate.detail,
                gate.remediation or "—",
            )
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.gate_table.resizeColumnsToContents()

        self.report_table.setRowCount(len(snapshot.reports))
        for row, report in enumerate(snapshot.reports):
            state = "Acknowledged" if report.acknowledged else "Review"
            values = (
                state,
                report.created_at,
                report.source,
                report.severity.title(),
                report.exception_type,
                report.summary,
                report.integrity_status.title(),
                report.report_id,
            )
            for column, value in enumerate(values):
                self.report_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.report_table.resizeColumnsToContents()
        self.status_label.setText(
            f"Session {snapshot.session_id or 'not started'} · database {snapshot.database_status} · "
            f"queue recovery {'available' if snapshot.queue_recovery_available else 'not pending'}"
        )
        if snapshot.reports:
            self.report_table.selectRow(0)
        else:
            self.detail.setPlainText("No structured crash report has been recorded.")

    def selected_report_id(self) -> str:
        row = self.report_table.currentRow()
        if row < 0:
            return ""
        item = self.report_table.item(row, 7)
        return item.text().strip() if item else ""

    def show_selected_report(self) -> None:
        report_id = self.selected_report_id()
        if not report_id:
            return
        try:
            payload = self.service.read_report(report_id)
        except Exception as exc:
            self.detail.setPlainText(f"Report cannot be displayed: {exc}")
            return
        self.detail.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    def acknowledge_selected(self):
        report_id = self.selected_report_id()
        if not report_id:
            self.status_label.setText("Select a crash report first.")
            return None
        try:
            record = self.service.acknowledge(report_id)
        except Exception as exc:
            self.status_label.setText(f"Acknowledgement failed: {exc}")
            return None
        self.refresh()
        self.status_label.setText(f"Acknowledged {record.report_id}")
        return record

    def export_bundle(self):
        report_id = self.selected_report_id()
        selected = [report_id] if report_id else None
        try:
            receipt = self.service.export_bundle(report_ids=selected)
        except Exception as exc:
            self.status_label.setText(f"Diagnostics export failed: {exc}")
            return None
        self.status_label.setText(f"Verified diagnostics bundle: {receipt.path.name}")
        if callable(self.open_path):
            self.open_path(receipt.path.parent)
        return receipt

    def copy_safe_mode_command(self) -> str:
        command = self.service.safe_mode_command()
        if callable(self.copy_path):
            self.copy_path(command)
        else:
            QApplication.clipboard().setText(command)
        self.status_label.setText("Safe-mode command copied. It is not executed automatically.")
        return command

    def open_crash_folder(self) -> None:
        if callable(self.open_path):
            self.open_path(self.service.root)
        self.status_label.setText(str(self.service.root))
