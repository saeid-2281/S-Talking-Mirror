from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget


class NotificationService(Protocol):
    """Small boundary around user notifications."""

    def information(self, title: str, message: str) -> None: ...
    def warning(self, title: str, message: str) -> None: ...
    def error(self, title: str, message: str) -> None: ...
    def confirmation(self, title: str, message: str) -> bool: ...
    def show_generation_summary(self, summary: dict) -> None: ...


class QtNotificationService:
    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent
        self.summary_dialogs: list[QDialog] = []

    def information(self, title: str, message: str) -> None:
        QMessageBox.information(self.parent, title, message)

    def warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self.parent, title, message)

    def error(self, title: str, message: str) -> None:
        QMessageBox.critical(self.parent, title, message)

    def confirmation(self, title: str, message: str) -> bool:
        return (
            QMessageBox.warning(
                self.parent,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def show_generation_summary(self, summary: dict) -> None:
        dialog = QDialog(self.parent)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle("Generation finished")
        layout = QVBoxLayout(dialog)
        lines = [
            f"Total: {summary.get('total', 0)}",
            f"Completed: {summary.get('completed', 0)}",
            f"Skipped: {summary.get('skipped', 0)}",
            f"Failed: {summary.get('failed', 0)}",
        ]
        if summary.get("elapsed_seconds") is not None:
            lines.append(f"Elapsed: {summary['elapsed_seconds']:.2f} s")
        layout.addWidget(QLabel("\n".join(lines)))
        close = QPushButton("Dismiss")
        close.clicked.connect(dialog.close)
        layout.addWidget(close)
        dialog.setModal(False)
        dialog.show()
        self.summary_dialogs.append(dialog)
        dialog.destroyed.connect(lambda *_: self._forget_summary(dialog))

    def _forget_summary(self, dialog: QDialog) -> None:
        if dialog in self.summary_dialogs:
            self.summary_dialogs.remove(dialog)

    def close_summaries(self) -> None:
        for dialog in list(self.summary_dialogs):
            dialog.close()
