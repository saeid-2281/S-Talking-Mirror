from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_launch_receipt import GenerationLaunchReceiptComparison
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationLaunchReceiptDriftDialog(QDialog):
    """Compare one launch receipt against a project baseline without exposing secrets."""

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
        comparison: GenerationLaunchReceiptComparison,
        parent: QWidget | None = None,
        *,
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.comparison = comparison
        self.export_dir = Path(export_dir or service.reports_dir / "launch-receipt-drift")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchReceiptDriftDialog")
        self.setWindowTitle("Generation launch drift")
        self.resize(1050, 690)
        self.setMinimumSize(700, 480)
        self._build()
        self._render()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Generation launch drift",
            "Compare a trusted project baseline with another launch receipt before reusing settings or investigating operational changes.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.summary_card = DialogStatusCard(
            "Launch comparison ready",
            "Drift metrics are calculated from secret-free receipt fields.",
            tone="info",
        )
        self.summary_card.setObjectName("generationLaunchDriftSummaryCard")
        metric_row = QHBoxLayout()
        metric_row.setContentsMargins(0, 7, 0, 0)
        metric_row.setSpacing(7)
        self.metric_values: dict[str, QLabel] = {}
        for key, caption in (
            ("changes", "Changes"),
            ("critical", "Critical"),
            ("warnings", "Warnings"),
            ("information", "Information"),
        ):
            card = QFrame()
            card.setObjectName("historyMetricCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(10, 7, 10, 7)
            layout.setSpacing(1)
            label = QLabel(caption)
            label.setObjectName("historyMetricCaption")
            value = QLabel("0")
            value.setObjectName("historyMetricValue")
            layout.addWidget(label)
            layout.addWidget(value)
            self.metric_values[key] = value
            metric_row.addWidget(card, 1)
        self.summary_card.layout().addLayout(metric_row)
        self.workspace.add_body_widget(self.summary_card)

        identity_section = DialogSection(
            "Compared receipts",
            "The baseline remains unchanged. This view only analyzes recorded launch decisions.",
        )
        self.identity_label = QLabel()
        self.identity_label.setObjectName("historySummaryText")
        self.identity_label.setWordWrap(True)
        self.identity_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        identity_section.add_widget(self.identity_label)
        self.workspace.add_body_widget(identity_section)

        changes_section = DialogSection(
            "Configuration drift",
            "Critical changes affect provider, output replacement, output destination, integrity or a rise to high planning risk.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("generationLaunchDriftTable")
        self.table.setHorizontalHeaderLabels(
            ["Category", "Setting", "Baseline", "Candidate", "Severity"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(300)
        self.table.horizontalHeader().setStretchLastSection(True)
        changes_section.add_widget(self.table, 1)
        self.workspace.add_body_widget(changes_section, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setWordWrap(True)
        self.copy_button = QPushButton("Copy comparison summary")
        self.copy_button.setObjectName("generationLaunchDriftCopyButton")
        self.copy_button.setIcon(action_icon("general.copy"))
        self.export_button = QPushButton("Export drift report")
        self.export_button.setObjectName("generationLaunchDriftExportButton")
        self.export_button.setIcon(action_icon("save"))
        close_button = QPushButton("Close")
        close_button.setObjectName("generationLaunchDriftCloseButton")
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(self.copy_button)
        self.workspace.add_footer_widget(self.export_button)
        self.workspace.add_footer_widget(close_button)

        self.copy_button.clicked.connect(self.copy_summary)
        self.export_button.clicked.connect(self.export_report)
        close_button.clicked.connect(self.close)

    def _render(self) -> None:
        comparison = self.comparison
        tone = "error" if comparison.critical_count else (
            "warning" if comparison.warning_count else "success"
        )
        self.summary_card.update_status(
            comparison.status.replace("_", " ").title(),
            comparison.summary,
            tone=tone,
        )
        self.metric_values["changes"].setText(f"{comparison.changed_count:,}")
        self.metric_values["critical"].setText(f"{comparison.critical_count:,}")
        self.metric_values["warnings"].setText(f"{comparison.warning_count:,}")
        self.metric_values["information"].setText(
            f"{comparison.information_count:,}"
        )
        self.identity_label.setText(
            "\n".join(
                (
                    f"Project: {comparison.candidate.project_name}",
                    f"Baseline: {comparison.baseline.receipt_id or comparison.baseline.path}",
                    f"Candidate: {comparison.candidate.receipt_id or comparison.candidate.path}",
                    f"Baseline integrity: {comparison.baseline.integrity_status}",
                    f"Candidate integrity: {comparison.candidate.integrity_status}",
                    f"Safe to reuse baseline assumptions: {'Yes' if comparison.safe_to_reuse else 'No'}",
                )
            )
        )
        self.table.setRowCount(len(comparison.changes))
        for row, change in enumerate(comparison.changes):
            values = (
                change.category,
                change.label,
                change.baseline_value,
                change.candidate_value,
                change.severity.title(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setData(Qt.UserRole, change.severity)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.status_label.setText(comparison.summary)

    def summary_text(self) -> str:
        comparison = self.comparison
        lines = [
            "S Talking generation launch drift",
            f"Project: {comparison.candidate.project_name}",
            f"Baseline: {comparison.baseline.receipt_id or comparison.baseline.path}",
            f"Candidate: {comparison.candidate.receipt_id or comparison.candidate.path}",
            f"Status: {comparison.status}",
            comparison.summary,
        ]
        lines.extend(
            f"{item.severity.upper()} · {item.label}: {item.baseline_value} -> {item.candidate_value}"
            for item in comparison.changes
        )
        return "\n".join(lines)

    def copy_summary(self) -> str:
        text = self.summary_text()
        QApplication.clipboard().setText(text)
        self.status_label.setText("Launch drift summary copied.")
        return text

    def export_report(self) -> tuple[Path, Path]:
        paths = self.service.export_comparison(self.comparison, self.export_dir)
        self.status_label.setText(
            f"Exported drift report: {paths[0].name} and {paths[1].name}"
        )
        return paths
