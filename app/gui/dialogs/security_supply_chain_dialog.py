from __future__ import annotations

from pathlib import Path

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
from app.services.security_supply_chain_service import SecuritySupplyChainService


class SecuritySupplyChainDialog(QDialog):
    """Inspect credential, SBOM, package-integrity and vulnerability evidence."""

    def __init__(
        self,
        service: SecuritySupplyChainService,
        parent: QWidget | None = None,
        *,
        open_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("securitySupplyChainDialog")
        self.setWindowTitle("Security and supply-chain hardening")
        self.resize(1220, 800)
        self.setMinimumSize(920, 640)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Security and supply-chain hardening",
            "Audit credential storage, dependency inventory, SPDX SBOM, package paths, DLL placement, signatures and vulnerability evidence without reading private project content.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting security evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        gate_section = DialogSection(
            "Security gates",
            "Blockers must be resolved before stable release. Warnings identify missing optional evidence or preview-only exceptions.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("securitySupplyChainGateTable")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Control", "Severity", "Evidence", "Action"]
        )
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gate_section.add_widget(self.gate_table)
        self.workspace.add_body_widget(gate_section)

        component_section = DialogSection(
            "Software component inventory",
            "Installed Python distributions are listed by name and version. No local paths, environment variables or credential values are included.",
        )
        self.component_table = QTableWidget(0, 4)
        self.component_table.setObjectName("securitySupplyChainComponentTable")
        self.component_table.setHorizontalHeaderLabels(["Component", "Version", "Type", "License"])
        self.component_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.component_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        component_section.add_widget(self.component_table)
        self.workspace.add_body_widget(component_section)

        artifact_section = DialogSection(
            "Audited artifacts",
            "Only artifact names, sizes, SHA-256 and verification status are displayed.",
        )
        self.artifact_table = QTableWidget(0, 5)
        self.artifact_table.setObjectName("securitySupplyChainArtifactTable")
        self.artifact_table.setHorizontalHeaderLabels(
            ["Role", "File", "Size", "Status", "SHA-256"]
        )
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.artifact_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        artifact_section.add_widget(self.artifact_table)
        self.workspace.add_body_widget(artifact_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        buttons = (
            ("Refresh", self.refresh, "general.refresh", False),
            ("Generate SPDX SBOM", self.generate_sbom, "report", True),
            ("Audit portable package", self.audit_package, "health", False),
            ("Scan dependencies", self.scan_dependencies, "warning", False),
            ("Export JSON and CSV", self.export_snapshot, "save", False),
            ("Open evidence folder", self.open_evidence_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in buttons:
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.clicked.connect(handler)
            if primary:
                button.setObjectName("dialogPrimaryAction")
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def refresh(self) -> None:
        snapshot = self.service.snapshot()
        self.current_snapshot = snapshot
        tone = "error" if snapshot.status == "blocked" else "warning" if snapshot.status == "attention" else "success"
        package = snapshot.package_path.name if snapshot.package_path else "not available"
        self.summary.update_status(
            snapshot.summary,
            (
                f"Credentials {snapshot.credential_backend} · "
                f"{snapshot.component_count} component(s) · package {package}"
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status.replace("_", " ").title(),
                gate.label,
                gate.severity.title(),
                gate.detail,
                gate.remediation or "—",
            )
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.gate_table.resizeColumnsToContents()

        components = self.service.component_inventory()
        visible = components[:200]
        self.component_table.setRowCount(len(visible))
        for row, component in enumerate(visible):
            values = (
                component.name,
                component.version,
                component.component_type,
                component.license_expression,
            )
            for column, value in enumerate(values):
                self.component_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.component_table.resizeColumnsToContents()

        self.artifact_table.setRowCount(len(snapshot.artifacts))
        for row, artifact in enumerate(snapshot.artifacts):
            values = (
                artifact.role.replace("_", " ").title(),
                artifact.path.name,
                self._size(artifact.size_bytes),
                artifact.status.title(),
                artifact.sha256,
            )
            for column, value in enumerate(values):
                self.artifact_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.artifact_table.resizeColumnsToContents()
        self.status_label.setText(
            f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s) · vulnerability scan {snapshot.vulnerability_status}"
        )

    def generate_sbom(self) -> Path:
        path = self.service.generate_sbom()
        self.refresh()
        self.status_label.setText(f"Verified SPDX SBOM: {path.name}")
        return path

    def audit_package(self):
        package = self.service.latest_portable_package()
        if package is None:
            self.status_label.setText("No portable ZIP is available for audit.")
            return None
        receipt = self.service.audit_package(package)
        self.refresh()
        self.status_label.setText(
            f"Package audit {receipt.status}: {receipt.issue_count} issue(s)"
        )
        return receipt

    def scan_dependencies(self) -> Path:
        path = self.service.run_vulnerability_scan()
        self.refresh()
        self.status_label.setText(f"Dependency scan evidence: {path.name}")
        return path

    def export_snapshot(self) -> tuple[Path, Path]:
        json_path, csv_path = self.service.export_snapshot()
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}")
        if callable(self.open_path):
            self.open_path(json_path.parent)
        return json_path, csv_path

    def open_evidence_folder(self) -> None:
        if callable(self.open_path):
            self.open_path(self.service.root)
        self.status_label.setText(str(self.service.root))

    @staticmethod
    def _size(value: int) -> str:
        if value < 1024:
            return f"{value} B"
        if value < 1024**2:
            return f"{value / 1024:.1f} KB"
        return f"{value / 1024**2:.1f} MB"
