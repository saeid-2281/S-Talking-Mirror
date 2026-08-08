from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.operational_persistence_service import OperationalPersistenceService


class OperationalPersistenceDialog(QDialog):
    """Database-backed operational evidence index with source artifacts preserved."""

    def __init__(
        self,
        service: OperationalPersistenceService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.setObjectName("operationalPersistenceDialog")
        self.setWindowTitle("Operational persistence & evidence store")
        self.resize(1240, 780)
        self.setMinimumSize(940, 620)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Operational persistence & evidence store",
            "Index verified operational evidence in SQLite while keeping the existing JSON and ZIP artifacts authoritative and backward-compatible.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard("Checking persistence", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        note = DialogSection(
            "Persistence contract",
            "Synchronization is explicit and append-only. It never edits or deletes source evidence, never publishes externally, and stores filenames rather than workstation paths.",
        )
        self.contract_label = QLabel("")
        self.contract_label.setWordWrap(True)
        note.add_widget(self.contract_label)
        self.workspace.add_body_widget(note)

        section = DialogSection(
            "Indexed evidence",
            "Latest verified records by operational evidence type.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Evidence type", "Records", "Latest status", "Artifact", "Recorded"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.table)
        self.workspace.add_body_widget(section)

        self.sync_section = DialogSection(
            "Latest synchronization",
            "A synchronization run records counts and verification outcomes but never changes source artifacts.",
        )
        self.sync_label = QLabel("No synchronization run recorded.")
        self.sync_label.setWordWrap(True)
        self.sync_section.add_widget(self.sync_label)
        self.workspace.add_body_widget(self.sync_section)

        buttons = QHBoxLayout()
        refresh_button = QPushButton(action_icon("general.refresh"), "Refresh status")
        refresh_button.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh_button)
        sync_button = QPushButton(action_icon("save"), "Synchronize verified latest evidence")
        sync_button.clicked.connect(self.synchronize)
        buttons.addWidget(sync_button)
        open_data = QPushButton(action_icon("project.output_folder"), "Open database folder")
        open_data.clicked.connect(self._open_database_folder)
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        self.workspace.add_footer_layout(buttons)

    def refresh_view(self) -> None:
        status = self.service.status()
        ok = bool(status["database_ok"])
        record_count = int(status["record_count"])
        tone = "success" if ok else "danger"
        self.overall.set_status(
            "VERIFIED" if ok else "ATTENTION",
            f"SQLite schema {status['schema_version']} · {record_count} indexed operational records · {status['database_detail']}",
            tone=tone,
        )
        contract = status["safety_contract"]
        self.contract_label.setText(
            "Source artifacts authoritative: yes · Database role: secondary index · "
            f"Automatic source mutation: {contract['automatic_source_mutation']} · "
            f"Automatic deletion: {contract['automatic_evidence_deletion']} · "
            f"Automatic publish: {contract['automatic_publish']}"
        )

        counts = status["counts_by_type"]
        latest = status["latest_by_type"]
        evidence_types = sorted(set(counts) | set(latest))
        self.table.setRowCount(len(evidence_types))
        for row, evidence_type in enumerate(evidence_types):
            record = latest.get(evidence_type)
            values = [
                evidence_type.replace("_", " ").title(),
                str(counts.get(evidence_type, 0)),
                record.status if record is not None else "—",
                record.artifact_filename if record is not None else "—",
                record.recorded_at if record is not None else "—",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

        latest_sync = status["latest_sync"]
        if latest_sync is None:
            self.sync_label.setText("No synchronization run recorded.")
        else:
            self.sync_label.setText(
                f"{latest_sync.status.upper()} · scanned {latest_sync.scanned} · imported {latest_sync.imported} · "
                f"unchanged {latest_sync.unchanged} · skipped {latest_sync.skipped} · failed {latest_sync.failed}\n"
                + "\n".join(f"• {item}" for item in latest_sync.details)
            )

    def synchronize(self) -> None:
        summary = self.service.sync_verified_latest()
        self.refresh_view()
        if summary.failed:
            QMessageBox.warning(
                self,
                "Operational persistence synchronization",
                f"Synchronization completed with {summary.failed} failed source(s). No source artifacts were changed.",
            )
        else:
            QMessageBox.information(
                self,
                "Operational persistence synchronization",
                f"Verified synchronization complete: {summary.imported} imported, {summary.unchanged} unchanged, {summary.skipped} unavailable.",
            )

    def _open_database_folder(self) -> None:
        if self.open_path is not None:
            self.open_path(Path(self.service.database.path).parent)
