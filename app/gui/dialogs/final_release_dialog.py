from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.final_release_service import FinalReleaseService


class FinalReleaseDialog(QDialog):
    """Inspect signing evidence and build deterministic update-channel packages."""

    def __init__(
        self,
        service: FinalReleaseService,
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
        self.setObjectName("finalReleaseDialog")
        self.setWindowTitle("Final release and update channel")
        self.resize(1160, 780)
        self.setMinimumSize(840, 600)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Signed release and update channel",
            "Verify Authenticode evidence, stage final artifacts and publish deterministic preview, beta or stable update metadata.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting final release evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(QLabel("Channel"))
        self.channel = QComboBox()
        self.channel.setObjectName("finalReleaseChannel")
        self.channel.addItems(["preview", "beta", "stable"])
        controls_layout.addWidget(self.channel)
        controls_layout.addWidget(QLabel("Rollout"))
        self.rollout = QSpinBox()
        self.rollout.setObjectName("finalReleaseRollout")
        self.rollout.setRange(1, 100)
        self.rollout.setValue(100)
        self.rollout.setSuffix("%")
        controls_layout.addWidget(self.rollout)
        controls_layout.addStretch(1)
        self.workspace.add_body_widget(controls)

        gate_section = DialogSection(
            "Final release gates",
            "Blockers protect release identity, update metadata and privacy. Missing signatures remain warnings unless strict signing is requested.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("finalReleaseGateTable")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Evidence", "Remediation"]
        )
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gate_section.add_widget(self.gate_table)
        self.workspace.add_body_widget(gate_section)

        signature_section = DialogSection(
            "Authenticode evidence",
            "Application and installer signatures are recorded without certificate private keys or passwords.",
        )
        self.signature_table = QTableWidget(0, 6)
        self.signature_table.setObjectName("finalReleaseSignatureTable")
        self.signature_table.setHorizontalHeaderLabels(
            ["Artifact", "Status", "Timestamp", "Subject", "Thumbprint", "Path"]
        )
        self.signature_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.signature_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        signature_section.add_widget(self.signature_table)
        self.workspace.add_body_widget(signature_section)

        self.require_installer = QCheckBox("Require Windows installer")
        self.require_installer.setObjectName("finalReleaseRequireInstaller")
        self.require_signatures = QCheckBox("Require verified signatures")
        self.require_signatures.setObjectName("finalReleaseRequireSignatures")
        self.workspace.add_footer_widget(self.require_installer)
        self.workspace.add_footer_widget(self.require_signatures)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)

        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        build = QPushButton("Build final release")
        build.setObjectName("dialogPrimaryAction")
        build.setIcon(action_icon("save"))
        build.clicked.connect(self.build_release)
        verify = QPushButton("Verify update feed")
        verify.clicked.connect(self.verify_feed)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        open_folder = QPushButton("Open final release folder")
        open_folder.clicked.connect(self.open_release_folder)
        copy_summary = QPushButton("Copy summary")
        copy_summary.clicked.connect(self.copy_summary)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for widget in (refresh, build, verify, export, open_folder, copy_summary, close):
            self.workspace.add_footer_widget(widget)

    def refresh(self) -> None:
        try:
            snapshot = self.service.snapshot(
                channel=self.channel.currentText(),
                rollout_percentage=self.rollout.value(),
            )
        except Exception as exc:
            self.status_label.setText(f"Refresh failed: {exc}")
            return
        self._render(snapshot)

    def _render(self, snapshot) -> None:
        self.current_snapshot = snapshot
        tone = (
            "success"
            if snapshot.status == "ready"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "error"
        )
        self.summary.update_status(
            snapshot.summary,
            f"Version {snapshot.version} · {snapshot.channel} · rollout {snapshot.rollout_percentage}% · {snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)",
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

        self.signature_table.setRowCount(len(snapshot.signatures))
        for row, evidence in enumerate(snapshot.signatures):
            values = (
                evidence.role.replace("_", " ").title(),
                evidence.status.title(),
                "Yes" if evidence.timestamped else "No",
                evidence.subject or "—",
                evidence.thumbprint or "—",
                str(evidence.path) if evidence.path else "—",
            )
            for column, value in enumerate(values):
                self.signature_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.signature_table.resizeColumnsToContents()
        self.status_label.setText(f"Release {snapshot.release_id}")

    def build_release(self):
        try:
            snapshot = self.service.build_final_release(
                channel=self.channel.currentText(),
                rollout_percentage=self.rollout.value(),
                require_installer=self.require_installer.isChecked(),
                require_signatures=self.require_signatures.isChecked(),
            )
        except Exception as exc:
            self.status_label.setText(f"Build failed: {exc}")
            return None
        self._render(snapshot)
        self.status_label.setText(f"Built and verified {snapshot.bundle_dir}")
        return snapshot

    def verify_feed(self) -> bool:
        feed = (
            self.current_snapshot.update_feed
            if self.current_snapshot and self.current_snapshot.update_feed
            else self.service.latest_channel_feed(self.channel.currentText())
        )
        if not feed.exists():
            self.status_label.setText("No update feed is available.")
            return False
        ok, detail = self.service.verify_update_feed(feed)
        self.status_label.setText(detail)
        return ok

    def export_snapshot(self):
        path = self.service.export_snapshot(self.current_snapshot)
        self.status_label.setText(f"Exported {path.name}")
        return path

    def open_release_folder(self) -> None:
        folder = self.service.latest_release_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if callable(self.open_path):
            self.open_path(folder)
        self.status_label.setText(str(folder))

    def copy_summary(self) -> str:
        snapshot = self.current_snapshot or self.service.snapshot()
        text = (
            f"S-Talking {snapshot.version} final release\n"
            f"Status: {snapshot.status}\n"
            f"Channel: {snapshot.channel}\n"
            f"Rollout: {snapshot.rollout_percentage}%\n"
            f"Application signature: {'verified' if snapshot.executable_signed else 'unsigned'}\n"
            f"Installer signature: {'verified' if snapshot.installer_signed else 'unsigned/unavailable'}\n"
            f"Bundle: {snapshot.bundle_dir or 'not built'}"
        )
        if callable(self.copy_path):
            self.copy_path(text)
        self.status_label.setText("Final release summary copied.")
        return text
