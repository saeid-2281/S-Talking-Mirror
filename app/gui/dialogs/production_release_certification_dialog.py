from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.production_release import ProductionCertificationSnapshot
from app.services.production_release_certification_service import (
    ProductionReleaseCertificationService,
)


class ProductionReleaseCertificationDialog(QDialog):
    """Final human-controlled production certification and promotion workspace."""

    def __init__(
        self,
        service: ProductionReleaseCertificationService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: ProductionCertificationSnapshot | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("productionReleaseCertificationDialog")
        self.setWindowTitle("Production release certification")
        self.resize(1260, 820)
        self.setMinimumSize(960, 660)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Production release readiness & 1.0 certification",
            "Aggregate quality, UX, security, stability, recovery, update and upgrade evidence into a tamper-evident release attestation. This workspace never publishes, tags, installs or changes the application version automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        settings = DialogSection(
            "Promotion identity",
            "Certification is bound to one immutable source commit and one stable semantic target version.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.target_version = QLineEdit("1.0.0")
        self.target_version.setObjectName("productionTargetVersion")
        self.target_version.setAccessibleName("Production target version")
        self.target_version.setPlaceholderText("1.0.0")
        form.addRow("Target version", self.target_version)
        self.source_commit = QLineEdit()
        self.source_commit.setObjectName("productionSourceCommit")
        self.source_commit.setAccessibleName("Source Git commit")
        self.source_commit.setPlaceholderText("Auto-detect current Git HEAD")
        form.addRow("Source commit", self.source_commit)
        self.expected_tests = QSpinBox()
        self.expected_tests.setObjectName("productionExpectedTests")
        self.expected_tests.setAccessibleName("Minimum passing test count")
        self.expected_tests.setRange(1, 100_000)
        self.expected_tests.setValue(850)
        form.addRow("Minimum passed tests", self.expected_tests)
        settings.add_widget(form_widget)
        self.workspace.add_body_widget(settings)

        self.summary = DialogStatusCard("Collecting production evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("productionCertificationTabs")
        self.tabs.setAccessibleName("Production certification evidence")
        self.workspace.add_body_widget(self.tabs, 1)

        self.gate_table = self._table(
            ["Status", "Category", "Gate", "Evidence", "Remediation"],
            "productionCertificationGateTable",
        )
        self.tabs.addTab(self._tab("Certification gates", self.gate_table), "Release gates")

        self.evidence_table = self._table(
            ["Role", "Status", "Artifact", "Size", "SHA-256", "Captured", "Detail"],
            "productionCertificationEvidenceTable",
        )
        self.tabs.addTab(self._tab("Evidence inventory", self.evidence_table), "Evidence")

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self.acknowledge = QCheckBox(
            "I reviewed every warning and understand that the plan still requires a separate version commit, rebuild, signature verification and manual stable-channel publication."
        )
        self.acknowledge.setObjectName("productionPromotionAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge manual production promotion plan")
        controls_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(controls)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Production certification status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh certification", self.refresh, "general.refresh", True),
            ("Write attestation", self.write_attestation, "save", False),
            ("Prepare promotion plan", self.prepare_plan, "report", False),
            ("Open evidence folder", self.open_evidence_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in actions:
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.setIcon(action_icon(icon_name))
            if primary:
                button.setObjectName("dialogPrimaryAction")
            button.clicked.connect(handler)
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.setAccessibleName("Close production certification")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    @staticmethod
    def _table(headers: list[str], object_name: str) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName(object_name)
        table.setAccessibleName(" ".join(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        return table

    @staticmethod
    def _tab(title: str, table: QTableWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        section = DialogSection(
            title,
            "Only structured metadata, statuses, sizes and hashes are displayed; private project and credential data are excluded.",
        )
        section.add_widget(table)
        layout.addWidget(section)
        return tab

    def _snapshot(self) -> ProductionCertificationSnapshot:
        return self.service.certification_snapshot(
            target_version=self.target_version.text().strip(),
            source_commit=self.source_commit.text().strip(),
            expected_test_count=self.expected_tests.value(),
        )

    def refresh(self) -> ProductionCertificationSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        tone = "error" if snapshot.status == "blocked" else "warning" if snapshot.status == "ready_with_warnings" else "success"
        self.summary.update_status(
            snapshot.summary,
            (
                f"{snapshot.source_version} → {snapshot.target_version or 'invalid target'} · "
                f"commit {snapshot.source_commit[:12] or 'not resolved'} · "
                f"{snapshot.observed_test_count}/{snapshot.expected_test_count} tests · "
                f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            self._set_row(
                self.gate_table,
                row,
                (
                    gate.status.replace("_", " ").title(),
                    gate.category.replace("-", " ").title(),
                    gate.label,
                    gate.detail,
                    gate.remediation or "—",
                ),
            )
        self.gate_table.resizeColumnsToContents()

        self.evidence_table.setRowCount(len(snapshot.evidence))
        for row, artifact in enumerate(snapshot.evidence):
            self._set_row(
                self.evidence_table,
                row,
                (
                    artifact.role.replace("_", " ").title(),
                    artifact.status.replace("_", " ").title(),
                    artifact.path.name,
                    self._format_bytes(artifact.size_bytes),
                    artifact.sha256[:16] if artifact.sha256 else "—",
                    artifact.captured_at or "unknown",
                    artifact.detail,
                ),
            )
        self.evidence_table.resizeColumnsToContents()
        self.status_label.setText(snapshot.summary)
        return snapshot

    def write_attestation(self) -> None:
        snapshot = self.refresh()
        path = self.service.write_attestation(snapshot)
        ok, detail = self.service.verify_attestation(path)
        self.current_snapshot = replace(snapshot, attestation_path=path)
        self.status_label.setText(f"Attestation written: {path.name} — {detail}")
        if not ok:
            QMessageBox.warning(self, "Attestation not promotion-eligible", detail)

    def prepare_plan(self) -> None:
        snapshot = self.current_snapshot or self.refresh()
        if snapshot.attestation_path is None:
            path = self.service.write_attestation(snapshot)
            snapshot = replace(snapshot, attestation_path=path)
            self.current_snapshot = snapshot
        result = self.service.create_promotion_plan(
            snapshot,
            acknowledge=self.acknowledge.isChecked(),
        )
        status = str(result.get("status") or "")
        detail = str(result.get("detail") or "")
        self.status_label.setText(detail)
        if status == "prepared":
            QMessageBox.information(self, "Promotion plan prepared", detail)
        elif status == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Promotion plan blocked", detail)

    def open_evidence_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)

    @staticmethod
    def _set_row(table: QTableWidget, row: int, values: tuple[str, ...]) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row, column, item)

    @staticmethod
    def _format_bytes(value: int) -> str:
        number = float(max(0, value))
        for suffix in ("B", "KB", "MB", "GB"):
            if number < 1024 or suffix == "GB":
                return f"{number:.1f} {suffix}" if suffix != "B" else f"{int(number)} B"
            number /= 1024
        return f"{int(value)} B"
