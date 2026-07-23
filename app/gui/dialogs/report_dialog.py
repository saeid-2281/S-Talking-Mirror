from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from app.models import GenerationReport


class ReportDialog(QDialog):
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
        self.setWindowTitle("Generation report")
        layout = QVBoxLayout(self)
        summary = report.summary
        layout.addWidget(
            QLabel(
                "\n".join(
                    [
                        f"Files: {summary.get('total_files', 0)}",
                        f"Completed: {summary.get('completed', 0)}",
                        f"Skipped: {summary.get('skipped', 0)}",
                        f"Failed: {summary.get('failed', 0)}",
                        f"Report: {report.report_dir}",
                    ]
                )
            )
        )
        actions = [
            ("Open report", lambda: open_report(report.report_html)),
            ("Open folder", lambda: open_folder(report.report_dir)),
            ("Copy path", lambda: copy_path(report.report_dir)),
            ("Export diagnostics", lambda: export_diagnostics(report.report_dir)),
            ("Close", self.close),
        ]
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
