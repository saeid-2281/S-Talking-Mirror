from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.final_production_certification import FinalProductionCertificationSnapshot
from app.services.final_production_certification_service import FinalProductionCertificationService


class FinalProductionCertificationDialog(QDialog):
    """Final S-Talking 1.x production certification workspace."""

    openRequested = Signal(str)

    def __init__(
        self,
        service: FinalProductionCertificationService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: FinalProductionCertificationSnapshot | None = None
        self.setObjectName("finalProductionCertificationDialog")
        self.setWindowTitle("Final S-Talking 1.x production certification")
        self.resize(1460, 900)
        self.setMinimumSize(1060, 720)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Final S-Talking 1.x production certification",
            "Bind the stable 1.x identity, committed source, post-commit release check, release artifacts and operational integrity into one final human-acknowledged certification.",
            icon_name="success",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard("Loading final certification", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        gates = DialogSection(
            "Final production gates",
            "Blockers prevent final certification. Supplemental release evidence is verified when present without replacing the authoritative post-commit release check.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Severity", "Detail", "Action"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.table)
        self.workspace.add_body_widget(gates)

        approval = DialogSection(
            "Human certification",
            "Creating the final attestation writes evidence only. It never publishes, tags, installs, updates, restarts, restores or rolls back the application.",
        )
        self.reviewer = QLineEdit()
        self.reviewer.setObjectName("finalProductionReviewer")
        self.reviewer.setPlaceholderText("Reviewer name or role")
        approval.add_widget(self.reviewer)
        self.statement = QLineEdit()
        self.statement.setObjectName("finalProductionStatement")
        self.statement.setPlaceholderText(
            "Final certification statement (no secrets or local paths)"
        )
        approval.add_widget(self.statement)
        self.acknowledge = QCheckBox(
            "I reviewed the final gates and acknowledge this certification evidence."
        )
        self.acknowledge.setObjectName("finalProductionAcknowledge")
        approval.add_widget(self.acknowledge)
        self.workspace.add_body_widget(approval)

        self.evidence = QLabel("")
        self.evidence.setWordWrap(True)
        self.workspace.add_body_widget(self.evidence)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Reassess")
        refresh.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh)
        certify = QPushButton(action_icon("save"), "Create final certification")
        certify.clicked.connect(self.create_certification)
        buttons.addWidget(certify)
        for label, code in (
            ("Release Lifecycle", "release-lifecycle"),
            ("Operational Readiness", "operational-readiness"),
            ("Persistence", "operational-persistence"),
            ("Production Release", "production-release"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=code: self.openRequested.emit(value)
            )
            buttons.addWidget(button)
        open_folder = QPushButton(
            action_icon("project.output_folder"),
            "Open certification evidence",
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
            if snapshot.status == "certified_with_warnings"
            else "success"
        )
        self.overall.update_status(
            snapshot.status.upper(),
            f"{snapshot.pass_count} passed · {snapshot.warning_count} warnings · "
            f"{snapshot.blocker_count} blockers · {snapshot.observed_test_count} tests · "
            f"commit {snapshot.source_commit[:12] or 'unavailable'}",
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.severity, gate.detail, gate.action)
            ):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        evidence_names = ", ".join(item.label for item in snapshot.sources)
        self.evidence.setText(
            f"Stable identity: {snapshot.version}/{snapshot.channel} · database schema "
            f"{snapshot.schema_version}\nBound evidence: "
            f"{evidence_names or 'post-commit evidence has not been exported yet'}"
        )

    def create_certification(self) -> None:
        snapshot = self.service.assess()
        result = self.service.create_certification(
            snapshot,
            reviewer=self.reviewer.text(),
            statement=self.statement.text(),
            acknowledge=self.acknowledge.isChecked(),
        )
        if result.get("status") in {"blocked", "dry_run"}:
            QMessageBox.warning(
                self,
                "Final certification not created",
                str(result.get("detail") or ""),
            )
            self.refresh_view()
            return
        attestation = Path(str(result.get("path") or ""))
        ok, detail = self.service.verify_attestation(attestation)
        if not ok:
            QMessageBox.critical(self, "Final certification verification failed", detail)
            return
        self.refresh_view()
        QMessageBox.information(
            self,
            "Final S-Talking 1.x certification created",
            f"{detail}\n\n{attestation.name}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
