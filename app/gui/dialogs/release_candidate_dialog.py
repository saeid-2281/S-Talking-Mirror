from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from app.services.release_candidate_service import ReleaseCandidateService


class ReleaseCandidateDialog(QDialog):
    """Build, inspect, and verify the final release-candidate bundle."""

    def __init__(
        self,
        service: ReleaseCandidateService,
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
        self.setObjectName("releaseCandidateDialog")
        self.setWindowTitle("Release candidate")
        self.resize(1120, 760)
        self.setMinimumSize(820, 580)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Release candidate and production readiness",
            "Verify release gates, package privacy, checksums, manifest integrity and rollback evidence before publishing.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting release evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        gates = DialogSection(
            "Release gates",
            "Blockers must pass before the candidate is approved. Warnings remain visible in release notes.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("releaseCandidateGateTable")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Evidence", "Remediation"]
        )
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        artifacts = DialogSection(
            "Candidate artifacts",
            "Portable package, release manifest, SHA-256 checksums and release notes are kept together.",
        )
        self.artifact_table = QTableWidget(0, 5)
        self.artifact_table.setObjectName("releaseCandidateArtifactTable")
        self.artifact_table.setHorizontalHeaderLabels(
            ["Role", "Status", "Size", "SHA-256", "Path"]
        )
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.artifact_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        artifacts.add_widget(self.artifact_table)
        self.workspace.add_body_widget(artifacts)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        build = QPushButton("Build release candidate")
        build.setObjectName("dialogPrimaryAction")
        build.setIcon(action_icon("save"))
        build.clicked.connect(self.build_candidate)
        verify = QPushButton("Verify manifest")
        verify.clicked.connect(self.verify_manifest)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        open_folder = QPushButton("Open candidate folder")
        open_folder.clicked.connect(self.open_candidate_folder)
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
        tone = "success" if snapshot.status == "ready" else "warning" if snapshot.status == "ready_with_warnings" else "error"
        self.summary.update_status(
            snapshot.summary,
            f"Version {snapshot.version} · commit {snapshot.commit} · {snapshot.test_count:,} tests · "
            f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)",
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
            f"Candidate {snapshot.candidate_id} · channel {snapshot.release_channel} · schema {snapshot.schema_version}"
        )

    def build_candidate(self):
        try:
            snapshot = self.service.build_candidate()
        except Exception as exc:
            self.status_label.setText(f"Build failed: {exc}")
            return None
        self._render_snapshot(snapshot)
        self.status_label.setText(
            f"Built candidate {snapshot.candidate_id} in "
            f"{snapshot.manifest_path.parent if snapshot.manifest_path else 'artifacts'}."
        )
        return snapshot

    def verify_manifest(self):
        snapshot = self.current_snapshot or self.service.snapshot()
        manifest = snapshot.manifest_path
        if manifest is None:
            latest = self.service.latest_candidate_dir() / self.service.MANIFEST_NAME
            manifest = latest if latest.exists() else None
        if manifest is None:
            self.status_label.setText("No release-candidate manifest is available.")
            return False
        ok, detail = self.service.verify_manifest(manifest)
        self.status_label.setText(detail)
        return ok

    def export_snapshot(self):
        snapshot = self.current_snapshot or self.service.snapshot()
        path = self.service.export_snapshot(snapshot)
        self.status_label.setText(f"Exported {path.name}")
        return path

    def open_candidate_folder(self) -> None:
        folder = self.service.latest_candidate_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if callable(self.open_path):
            self.open_path(folder)
        self.status_label.setText(str(folder))

    def copy_summary(self) -> str:
        snapshot = self.current_snapshot or self.service.snapshot()
        text = (
            f"S-Talking {snapshot.version} ({snapshot.release_channel})\n"
            f"Commit: {snapshot.commit}\n"
            f"Status: {snapshot.status}\n"
            f"Tests: {snapshot.test_count}\n"
            f"Blockers: {snapshot.blocker_count}\n"
            f"Warnings: {snapshot.warning_count}\n"
            f"Package: {snapshot.package_path or 'not built'}"
        )
        if callable(self.copy_path):
            self.copy_path(text)
        self.status_label.setText("Release summary copied.")
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
