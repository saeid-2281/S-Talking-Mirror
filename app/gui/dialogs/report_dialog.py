from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models import GenerationReport


class ReportDialog(QDialog):
    """Readable non-modal report summary with stable paths and actions."""

    def __init__(
        self,
        report: GenerationReport,
        parent: QWidget | None = None,
        *,
        open_report: Callable[[Path], None],
        open_folder: Callable[[Path], None],
        copy_path: Callable[[Path], None],
        export_diagnostics: Callable[[Path], None],
    ) -> None:
        super().__init__(parent)
        self.report = report
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setModal(False)
        self.setObjectName("generationReportDialog")
        self.setWindowTitle("Generation report")
        self.resize(760, 590)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Generation report",
            "Review the final batch outcome, open the HTML report and keep diagnostics or paths available for follow-up.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        summary = report.summary
        total = int(summary.get("total_files", summary.get("total", 0)) or 0)
        completed = int(summary.get("completed", 0) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        failed = int(summary.get("failed", 0) or 0)
        success_rate = (completed / total * 100.0) if total else 0.0
        tone = "error" if failed else "warning" if skipped else "success"
        status_title = "Generation completed with failures" if failed else "Generation completed with skipped jobs" if skipped else "Generation completed successfully"
        self.status_card = DialogStatusCard(
            status_title,
            f"{completed:,} of {total:,} files completed · {success_rate:.1f}% completion rate",
            tone=tone,
        )
        self.status_card.setObjectName("reportStatusCard")

        metrics = QHBoxLayout()
        metrics.setContentsMargins(0, 7, 0, 0)
        metrics.setSpacing(7)
        self.metric_values: dict[str, QLabel] = {}
        for key, caption, value in (
            ("total", "Files", f"{total:,}"),
            ("completed", "Completed", f"{completed:,}"),
            ("skipped", "Skipped", f"{skipped:,}"),
            ("failed", "Failed", f"{failed:,}"),
        ):
            card = QFrame()
            card.setObjectName("reportMetricCard")
            card.setProperty("tone", "error" if key == "failed" and failed else "warning" if key == "skipped" and skipped else "neutral")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(11, 8, 11, 8)
            card_layout.setSpacing(1)
            label = QLabel(caption)
            label.setObjectName("reportMetricCaption")
            number = QLabel(value)
            number.setObjectName("reportMetricValue")
            card_layout.addWidget(label)
            card_layout.addWidget(number)
            self.metric_values[key] = number
            metrics.addWidget(card, 1)
        self.status_card.layout().addLayout(metrics)
        self.workspace.add_body_widget(self.status_card)

        location_section = DialogSection(
            "Report location",
            "All report artifacts belong to this run. The HTML report, CSV exports and diagnostics remain inside this folder.",
        )
        location_section.setObjectName("reportLocationSection")
        self.path_label = QLabel(str(report.report_dir))
        self.path_label.setObjectName("reportPathLabel")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.html_label = QLabel(f"HTML report: {report.report_html}")
        self.html_label.setObjectName("reportHtmlPathLabel")
        self.html_label.setWordWrap(True)
        self.html_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        location_section.add_widget(self.path_label)
        location_section.add_widget(self.html_label)
        self.workspace.add_body_widget(location_section)

        details_section = DialogSection(
            "Run context",
            "The summary below is taken directly from the generated report metadata.",
        )
        details_section.setObjectName("reportContextSection")
        context_rows = []
        for label, key in (
            ("Project", "project_name"),
            ("Provider", "provider"),
            ("Model", "model"),
            ("Voice", "voice"),
            ("Started", "started_at"),
            ("Ended", "ended_at"),
            ("Output", "output_dir"),
        ):
            value = summary.get(key)
            if value not in (None, ""):
                context_rows.append(f"{label}: {value}")
        self.summary_label = QLabel("\n".join(context_rows) or "No additional run context is available.")
        self.summary_label.setObjectName("reportContextText")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_section.add_widget(self.summary_label)
        self.workspace.add_body_widget(details_section)
        self.workspace.add_body_stretch(1)

        self.open_report_button = QPushButton("Open report")
        self.open_report_button.setObjectName("reportPrimaryAction")
        self.open_report_button.setIcon(action_icon("report"))
        self.open_folder_button = QPushButton("Open folder")
        self.open_folder_button.setIcon(action_icon("project.output_folder"))
        self.copy_path_button = QPushButton("Copy path")
        self.copy_path_button.setIcon(action_icon("general.copy"))
        self.export_diagnostics_button = QPushButton("Export diagnostics")
        self.export_diagnostics_button.setIcon(action_icon("save"))
        self.close_button = QPushButton("Close")

        self.open_report_button.clicked.connect(lambda: open_report(report.report_html))
        self.open_folder_button.clicked.connect(lambda: open_folder(report.report_dir))
        self.copy_path_button.clicked.connect(lambda: copy_path(report.report_dir))
        self.export_diagnostics_button.clicked.connect(lambda: export_diagnostics(report.report_dir))
        self.close_button.clicked.connect(self.close)

        self.workspace.add_footer_widget(self.open_folder_button)
        self.workspace.add_footer_widget(self.copy_path_button)
        self.workspace.add_footer_widget(self.export_diagnostics_button)
        self.workspace.add_footer_stretch(1)
        self.workspace.add_footer_widget(self.open_report_button)
        self.workspace.add_footer_widget(self.close_button)
