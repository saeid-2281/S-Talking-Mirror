from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
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
from app.models.operations_command_center import OperationsCommandSnapshot
from app.services.operations_command_center_service import OperationsCommandCenterService


class OperationsCommandCenterDialog(QDialog):
    """Unified, read-only production operations workspace."""

    openRequested = Signal(str)

    def __init__(
        self,
        service: OperationsCommandCenterService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.open_path = open_path
        self.current_snapshot: OperationsCommandSnapshot | None = None
        self.setObjectName("operationsCommandCenterDialog")
        self.setWindowTitle("Production operations command center")
        self.resize(1420, 900)
        self.setMinimumSize(1040, 700)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Production operations command center",
            "One read-only view across production health, incidents, SLO, capacity, recovery, providers, billing and assurance. Evidence is verified in place; no operational change is executed automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard("Loading operational evidence", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        counters = QWidget()
        counter_layout = QHBoxLayout(counters)
        counter_layout.setContentsMargins(0, 0, 0, 0)
        self.healthy_label = QLabel("Healthy 0")
        self.warning_label = QLabel("Warning 0")
        self.critical_label = QLabel("Critical 0")
        self.unknown_label = QLabel("Unknown 0")
        for label in (
            self.healthy_label,
            self.warning_label,
            self.critical_label,
            self.unknown_label,
        ):
            label.setObjectName("operationsCommandCounter")
            counter_layout.addWidget(label)
        counter_layout.addStretch(1)
        self.workspace.add_body_widget(counters)

        section = DialogSection(
            "Operational domains",
            "Open a specialist workspace from the last column when a domain needs attention.",
        )
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Domain", "Status", "Key metric", "Summary", "Evidence", "Action"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.table)
        self.workspace.add_body_widget(section)

        recommendations = DialogSection(
            "Next review",
            "The command center never performs the recommended operation itself.",
        )
        self.recommendations = QLabel("")
        self.recommendations.setWordWrap(True)
        recommendations.add_widget(self.recommendations)
        self.workspace.add_body_widget(recommendations)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Refresh")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        export_button = QPushButton(action_icon("save"), "Export verified snapshot")
        export_button.clicked.connect(self.export_snapshot)
        buttons.addWidget(export_button)
        open_folder = QPushButton(
            action_icon("project.output_folder"), "Open command-center evidence"
        )
        open_folder.clicked.connect(lambda: self._open(self.service.root))
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        self.workspace.add_footer_layout(buttons)

    def refresh(self) -> None:
        snapshot = self.service.snapshot(project_id=self.project_id)
        self.current_snapshot = snapshot
        tone = (
            "danger"
            if snapshot.overall_status == "critical"
            else "warning"
            if snapshot.overall_status == "attention"
            else "success"
        )
        self.overall.set_status(
            snapshot.overall_status.upper(), snapshot.status_summary, tone=tone
        )
        self.healthy_label.setText(f"Healthy {snapshot.healthy_count}")
        self.warning_label.setText(f"Warning {snapshot.warning_count}")
        self.critical_label.setText(f"Critical {snapshot.critical_count}")
        self.unknown_label.setText(f"Unknown {snapshot.unknown_count}")
        self.recommendations.setText("\n".join(f"• {item}" for item in snapshot.recommendations))
        self._fill(snapshot)

    def _fill(self, snapshot: OperationsCommandSnapshot) -> None:
        self.table.setRowCount(len(snapshot.domains))
        for row, domain in enumerate(snapshot.domains):
            values = [
                domain.label,
                domain.status,
                domain.metric,
                domain.headline,
                domain.evidence_filename or "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(domain.detail if column in {2, 3, 4} else value)
                self.table.setItem(row, column, item)
            button = QPushButton("Open")
            button.setEnabled(bool(domain.action_code))
            button.clicked.connect(
                lambda _checked=False, code=domain.action_code: self.openRequested.emit(code)
            )
            self.table.setCellWidget(row, 5, button)
        self.table.resizeColumnsToContents()

    def export_snapshot(self) -> None:
        if self.current_snapshot is None:
            self.refresh()
        assert self.current_snapshot is not None
        path = self.service.export_snapshot(self.current_snapshot)
        ok, detail = self.service.verify_snapshot(path)
        if not ok:
            QMessageBox.critical(self, "Snapshot verification failed", detail)
            return
        QMessageBox.information(
            self,
            "Operations snapshot exported",
            f"Verified read-only snapshot:\n{path.name}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
