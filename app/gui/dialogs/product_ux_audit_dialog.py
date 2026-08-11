from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.product_ux_audit_service import ProductUXAuditService


class ProductUXAuditDialog(QDialog):
    """Roadmap 2 A1 product-experience audit workspace."""

    def __init__(
        self,
        service: ProductUXAuditService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot = None
        self.setObjectName("productUXAuditDialog")
        self.setWindowTitle("Product UX Audit / Workflow Baseline — Roadmap 2 A1")
        self.resize(1320, 820)
        self.setMinimumSize(1000, 640)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Product UX Audit / Workflow Baseline",
            "Roadmap 2 · Track A · Phase A1. Audit the complete user journey before redesign. Assessment is read-only; it does not switch providers, refresh catalogs, mutate the database, or start generation.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.overall = DialogStatusCard("Assessing product journeys", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        journey_section = DialogSection(
            "Core product journeys",
            "Ten user journeys are evaluated against deterministic source evidence so later UX changes can be compared to one stable baseline.",
        )
        self.journey_table = QTableWidget(0, 6)
        self.journey_table.setHorizontalHeaderLabels(
            ["Stage", "Journey", "Score", "Status", "Required gaps", "Opportunities"]
        )
        self.journey_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.journey_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.journey_table.horizontalHeader().setStretchLastSection(True)
        journey_section.add_widget(self.journey_table)
        self.workspace.add_body_widget(journey_section)

        backlog_section = DialogSection(
            "Priority UX backlog",
            "This is evidence-derived planning input, not an automatic redesign queue. Product changes remain explicit roadmap decisions.",
        )
        self.backlog_table = QTableWidget(0, 5)
        self.backlog_table.setHorizontalHeaderLabels(
            ["Priority", "Journey", "Opportunity", "Rationale", "Recommended action"]
        )
        self.backlog_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.backlog_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.backlog_table.horizontalHeader().setStretchLastSection(True)
        backlog_section.add_widget(self.backlog_table)
        self.workspace.add_body_widget(backlog_section)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Refresh audit")
        refresh.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh)
        export = QPushButton(action_icon("save"), "Export baseline snapshot")
        export.clicked.connect(self.export_snapshot)
        buttons.addWidget(export)
        open_folder = QPushButton(action_icon("project.output_folder"), "Open audit folder")
        open_folder.clicked.connect(lambda: self._open(self.service.root))
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        self.workspace.footer_layout.addLayout(buttons)

    def refresh_view(self) -> None:
        snapshot = self.service.assess()
        self.current_snapshot = snapshot
        tone = "danger" if snapshot.blocker_count else "warning" if snapshot.opportunity_count else "success"
        self.overall.update_status(
            snapshot.status.replace("_", " ").upper(),
            f"{snapshot.overall_score}/100 overall · {len(snapshot.journeys)} journeys · "
            f"{snapshot.blocker_count} structural gaps · {snapshot.opportunity_count} opportunities",
            tone=tone,
        )
        self.journey_table.setRowCount(len(snapshot.journeys))
        for row, journey in enumerate(snapshot.journeys):
            values = (
                journey.stage,
                journey.label,
                f"{journey.score}/100",
                journey.status.replace("_", " ").title(),
                journey.required_gap_count,
                journey.opportunity_count,
            )
            for column, value in enumerate(values):
                self.journey_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.journey_table.resizeColumnsToContents()

        self.backlog_table.setRowCount(len(snapshot.backlog))
        for row, item in enumerate(snapshot.backlog):
            values = (
                f"P{item.priority}",
                item.journey_label,
                item.title,
                item.rationale,
                item.action,
            )
            for column, value in enumerate(values):
                self.backlog_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.backlog_table.resizeColumnsToContents()

    def export_snapshot(self) -> None:
        if self.current_snapshot is None:
            self.refresh_view()
        path = self.service.export_snapshot(self.current_snapshot)
        ok, detail = self.service.verify_snapshot(path)
        if not ok:
            QMessageBox.warning(self, "Product UX audit verification failed", detail)
            return
        QMessageBox.information(
            self,
            "Product UX baseline exported",
            "Tamper-evident Roadmap 2 A1 baseline saved.\n\n" + str(path),
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
