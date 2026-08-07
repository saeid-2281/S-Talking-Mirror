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
from app.models.evidence_refresh import EvidenceRefreshSnapshot
from app.services.evidence_refresh_service import EvidenceRefreshService


class EvidenceRefreshDialog(QDialog):
    """Read-only evidence freshness and certification refresh workspace."""

    def __init__(
        self,
        service: EvidenceRefreshService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.open_path = open_path
        self.current_snapshot: EvidenceRefreshSnapshot | None = None
        self.setObjectName("evidenceRefreshDialog")
        self.setWindowTitle("Evidence & certification refresh")
        self.resize(1360, 860)
        self.setMinimumSize(980, 680)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Evidence & certification refresh",
            "Track freshness across operational evidence and create new read-only refresh records without mutating source evidence or production state.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard("Loading evidence registry", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        counters = QWidget()
        layout = QHBoxLayout(counters)
        layout.setContentsMargins(0, 0, 0, 0)
        self.counter_labels = {
            "fresh": QLabel("Fresh 0"),
            "due_soon": QLabel("Due soon 0"),
            "expired": QLabel("Expired 0"),
            "missing": QLabel("Missing 0"),
            "blocked": QLabel("Blocked 0"),
        }
        for label in self.counter_labels.values():
            label.setObjectName("evidenceRefreshCounter")
            layout.addWidget(label)
        layout.addStretch(1)
        self.workspace.add_body_widget(counters)

        section = DialogSection(
            "Evidence freshness registry",
            "Age policy is evaluated against verified operational evidence already produced by specialist workspaces.",
        )
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Domain", "Freshness", "Age", "Policy", "Evidence", "Verification"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.table)
        self.workspace.add_body_widget(section)

        next_review = DialogSection(
            "Refresh recommendations",
            "Refresh creates derived evidence only; it never deploys, restarts, publishes or changes provider/billing state.",
        )
        self.recommendations = QLabel("")
        self.recommendations.setWordWrap(True)
        next_review.add_widget(self.recommendations)
        self.workspace.add_body_widget(next_review)

        buttons = QHBoxLayout()
        refresh_button = QPushButton(action_icon("general.refresh"), "Reassess freshness")
        refresh_button.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh_button)
        certify_button = QPushButton(action_icon("save"), "Create certification refresh")
        certify_button.clicked.connect(self.create_certification_refresh)
        buttons.addWidget(certify_button)
        open_folder = QPushButton(action_icon("project.output_folder"), "Open refresh evidence")
        open_folder.clicked.connect(lambda: self._open(self.service.root))
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        self.workspace.add_footer_layout(buttons)

    def refresh_view(self) -> None:
        snapshot = self.service.assess(project_id=self.project_id)
        self.current_snapshot = snapshot
        tone = (
            "danger"
            if snapshot.overall_status == "blocked"
            else "warning"
            if snapshot.overall_status == "attention"
            else "success"
        )
        self.overall.set_status(
            snapshot.overall_status.upper(),
            f"{snapshot.count('fresh')} fresh · {snapshot.count('due_soon')} due soon · {snapshot.count('expired')} expired · {snapshot.count('missing')} missing · {snapshot.count('blocked')} blocked",
            tone=tone,
        )
        for status, label in self.counter_labels.items():
            label.setText(f"{status.replace('_', ' ').title()} {snapshot.count(status)}")
        self.recommendations.setText("\n".join(f"• {item}" for item in snapshot.recommendations))
        self.table.setRowCount(len(snapshot.entries))
        for row, item in enumerate(snapshot.entries):
            age = "—" if item.age_days is None else f"{item.age_days:.1f} d"
            policy = f"≤ {item.max_age_days} d"
            values = [
                item.label,
                item.status,
                age,
                policy,
                item.evidence_filename or "—",
                item.verification_detail,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def create_certification_refresh(self) -> None:
        registry, certification = self.service.refresh_certification(project_id=self.project_id)
        ok, detail = self.service.verify_certification(certification)
        if not ok:
            QMessageBox.critical(self, "Certification refresh failed", detail)
            return
        self.refresh_view()
        QMessageBox.information(
            self,
            "Certification refresh created",
            f"Verified read-only refresh:\n{registry.name}\n{certification.name}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
