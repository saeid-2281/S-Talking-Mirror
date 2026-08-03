from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.distribution_readiness_service import DistributionReadinessService


class DistributionReadinessDialog(QDialog):
    """Inspect installer, upgrade, rollback, and distribution evidence."""

    def __init__(
        self,
        service: DistributionReadinessService,
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
        self.setObjectName("distributionReadinessDialog")
        self.setWindowTitle("Distribution readiness")
        self.resize(1120, 760)
        self.setMinimumSize(820, 580)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Installer, upgrade and distribution readiness",
            "Validate the immutable release candidate, per-user installer, upgrade safety, rollback evidence and distribution checksums.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting distribution evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        gate_section = DialogSection(
            "Distribution gates",
            "Blockers protect package integrity and user data. A missing compiled installer is a warning when portable distribution is allowed.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("distributionGateTable")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Evidence", "Remediation"]
        )
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gate_section.add_widget(self.gate_table)
        self.workspace.add_body_widget(gate_section)

        artifact_section = DialogSection(
            "Distribution artifacts",
            "Portable ZIP, optional installer, release evidence, upgrade plan, rollback guide, manifest and SHA-256 checksums.",
        )
        self.artifact_table = QTableWidget(0, 5)
        self.artifact_table.setObjectName("distributionArtifactTable")
        self.artifact_table.setHorizontalHeaderLabels(
            ["Role", "Status", "Size", "SHA-256", "Path"]
        )
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.artifact_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        artifact_section.add_widget(self.artifact_table)
        self.workspace.add_body_widget(artifact_section)

        self.require_installer = QCheckBox("Require compiled Windows installer")
        self.require_installer.setObjectName("distributionRequireInstaller")
        self.workspace.add_footer_widget(self.require_installer)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)

        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        build = QPushButton("Build distribution bundle")
        build.setObjectName("dialogPrimaryAction")
        build.setIcon(action_icon("save"))
        build.clicked.connect(self.build_bundle)
        verify = QPushButton("Verify manifest")
        verify.clicked.connect(self.verify_manifest)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        open_folder = QPushButton("Open distribution folder")
        open_folder.clicked.connect(self.open_distribution_folder)
        copy_summary = QPushButton("Copy summary")
        copy_summary.clicked.connect(self.copy_summary)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for widget in (refresh, build, verify, export, open_folder, copy_summary, close):
            self.workspace.add_footer_widget(widget)

    def refresh(self) -> None:
        self._render_snapshot(self.service.snapshot())

    def _render_snapshot(self, snapshot) -> None:
        self.current_snapshot = snapshot
        tone = (
            "success"
            if snapshot.status == "ready"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "error"
        )
        installer = "installer ready" if snapshot.installer_distributable else "portable only"
        self.summary.update_status(
            snapshot.summary,
            f"Version {snapshot.version} · {installer} · {snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)",
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
        self._fill_artifacts(snapshot.artifacts)
        self.status_label.setText(
            f"Distribution {snapshot.distribution_id} · channel {snapshot.release_channel}"
        )

    def build_bundle(self):
        try:
            snapshot = self.service.build_distribution(
                require_installer=self.require_installer.isChecked()
            )
        except Exception as exc:
            self.status_label.setText(f"Build failed: {exc}")
            return None
        self._render_snapshot(snapshot)
        self.status_label.setText(f"Built and verified {snapshot.bundle_dir}")
        return snapshot

    def verify_manifest(self):
        folder = (
            self.current_snapshot.bundle_dir
            if self.current_snapshot and self.current_snapshot.bundle_dir
            else self.service.latest_distribution_dir()
        )
        manifest = folder / self.service.MANIFEST_NAME
        if not manifest.exists():
            self.status_label.setText("No distribution manifest is available.")
            return False
        ok, detail = self.service.verify_distribution_manifest(manifest)
        self.status_label.setText(detail)
        return ok

    def export_snapshot(self):
        path = self.service.export_snapshot(self.current_snapshot)
        self.status_label.setText(f"Exported {path.name}")
        return path

    def open_distribution_folder(self) -> None:
        folder = self.service.latest_distribution_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if callable(self.open_path):
            self.open_path(folder)
        self.status_label.setText(str(folder))

    def copy_summary(self) -> str:
        snapshot = self.current_snapshot or self.service.snapshot()
        text = (
            f"S-Talking {snapshot.version} distribution\n"
            f"Status: {snapshot.status}\n"
            f"Installer: {'verified' if snapshot.installer_distributable else 'not included'}\n"
            f"Blockers: {snapshot.blocker_count}\n"
            f"Warnings: {snapshot.warning_count}\n"
            f"Bundle: {snapshot.bundle_dir or 'not built'}"
        )
        if callable(self.copy_path):
            self.copy_path(text)
        self.status_label.setText("Distribution summary copied.")
        return text

    def _fill_artifacts(self, artifacts) -> None:
        self.artifact_table.setRowCount(len(artifacts))
        for row, artifact in enumerate(artifacts):
            values = (
                artifact.role.replace("_", " ").title(),
                artifact.status.title(),
                self._format_bytes(artifact.size_bytes),
                artifact.sha256[:16] + "…" if artifact.sha256 else "—",
                str(artifact.path),
            )
            for column, value in enumerate(values):
                self.artifact_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.artifact_table.resizeColumnsToContents()

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = max(0, int(value))
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.2f} MB"
