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
from app.models.release_lifecycle_validation import ReleaseLifecycleSnapshot
from app.services.release_lifecycle_validation_service import ReleaseLifecycleValidationService


class ReleaseLifecycleValidationDialog(QDialog):
    """End-to-end release, update and recovery validation workspace."""

    openRequested = Signal(str)

    def __init__(
        self,
        service: ReleaseLifecycleValidationService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: ReleaseLifecycleSnapshot | None = None
        self.setObjectName("releaseLifecycleValidationDialog")
        self.setWindowTitle("Installer / update / recovery end-to-end validation")
        self.resize(1420, 880)
        self.setMinimumSize(1040, 700)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Installer / update / recovery end-to-end validation",
            "Verify stable release provenance, update-client compatibility, installer handoff, database migration and recovery evidence as one guarded chain.",
            icon_name="history",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard("Loading lifecycle validation", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        section = DialogSection(
            "End-to-end lifecycle gates",
            "Blockers prevent release handoff. Validation never downloads, installs, restarts, restores, rolls back or publishes automatically.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Severity", "Detail", "Action"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.table)
        self.workspace.add_body_widget(section)

        self.evidence = QLabel("")
        self.evidence.setWordWrap(True)
        self.workspace.add_body_widget(self.evidence)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Reassess")
        refresh.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh)
        export = QPushButton(action_icon("save"), "Export verified snapshot")
        export.clicked.connect(self.export_snapshot)
        buttons.addWidget(export)
        for label, code in (
            ("Final Release", "final-release"),
            ("Update Delivery", "update-delivery"),
            ("Upgrade & Recovery", "upgrade-recovery"),
            ("Stable Promotion", "stable-release"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=code: self.openRequested.emit(value)
            )
            buttons.addWidget(button)
        open_folder = QPushButton(
            action_icon("project.output_folder"),
            "Open evidence folder",
        )
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
        tone = (
            "danger"
            if snapshot.status == "blocked"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "success"
        )
        self.overall.update_status(
            snapshot.status.upper(),
            f"{snapshot.pass_count} passed · {snapshot.warning_count} warnings · "
            f"{snapshot.blocker_count} blockers · schema "
            f"{snapshot.current_schema}→{snapshot.target_schema}",
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.severity, gate.detail, gate.action)
            ):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        names = ", ".join(item.label for item in snapshot.sources)
        if not names:
            names = "No managed source evidence is currently available."
        self.evidence.setText(
            f"Update status: {snapshot.update_status} · Selected package: "
            f"{snapshot.update_artifact or 'none'}\nBound evidence: {names}"
        )

    def export_snapshot(self) -> None:
        snapshot = self.service.assess()
        path = self.service.export_snapshot(snapshot)
        ok, detail = self.service.verify_snapshot(path)
        if not ok:
            QMessageBox.critical(
                self,
                "Lifecycle snapshot verification failed",
                detail,
            )
            return
        QMessageBox.information(
            self,
            "Lifecycle snapshot exported",
            f"{detail}\n\n{path.name}",
        )
        self.refresh_view()

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
