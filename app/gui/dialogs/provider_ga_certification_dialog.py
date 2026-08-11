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
from app.services.provider_ga_certification_service import ProviderGACertificationService


class ProviderGACertificationDialog(QDialog):
    """Final provider-track GA evidence workspace."""

    def __init__(
        self,
        service: ProviderGACertificationService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot = None
        self.setObjectName("providerGACertificationDialog")
        self.setWindowTitle("Provider Track Production Certification / GA")
        self.resize(1280, 780)
        self.setMinimumSize(980, 620)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Provider Track Production Certification / GA",
            "Bind the Phase 98–111 provider architecture to the existing production certification. This workspace writes evidence only; publish, tag, install, provider changes and generation remain explicit human actions.",
            icon_name="success",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.overall = DialogStatusCard("Assessing provider GA", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        section = DialogSection(
            "GA certification gates",
            "Base production integrity, source custody, built-in provider registry, Danish governance, routing/recovery authority and Plugin SDK boundaries are assessed together.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Gate", "Status", "Severity", "Detail", "Action"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.table)
        self.workspace.add_body_widget(section)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Refresh")
        refresh.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh)
        snapshot = QPushButton(action_icon("save"), "Export snapshot")
        snapshot.clicked.connect(self.export_snapshot)
        buttons.addWidget(snapshot)
        self.attest_button = QPushButton(action_icon("success"), "Export machine GA attestation")
        self.attest_button.clicked.connect(self.export_attestation)
        buttons.addWidget(self.attest_button)
        open_folder = QPushButton(action_icon("project.output_folder"), "Open evidence folder")
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
        tone = "danger" if snapshot.blocker_count else "warning" if snapshot.warning_count else "success"
        self.overall.update_status(
            snapshot.status.replace("_", " ").upper(),
            f"{snapshot.pass_count} pass · {snapshot.warning_count} warning · {snapshot.blocker_count} blocker · "
            f"{snapshot.observed_test_count} post-commit tests · {snapshot.builtin_provider_count} built-in providers",
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.label,
                gate.status.upper(),
                gate.severity.title(),
                gate.detail,
                gate.action or "—",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.attest_button.setEnabled(snapshot.blocker_count == 0)

    def export_snapshot(self) -> None:
        if self.current_snapshot is None:
            self.refresh_view()
        path = self.service.export_snapshot(self.current_snapshot)
        QMessageBox.information(self, "Provider GA snapshot exported", str(path))

    def export_attestation(self) -> None:
        if self.current_snapshot is None:
            self.refresh_view()
        result = self.service.create_attestation(self.current_snapshot)
        if result.get("status") == "blocked":
            QMessageBox.warning(self, "Provider GA blocked", str(result.get("detail") or "GA blockers remain."))
            return
        QMessageBox.information(
            self,
            "Provider GA evidence exported",
            "Machine GA attestation and audit pack verified. Human release promotion is still required.\n\n"
            + str(result.get("path") or ""),
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
