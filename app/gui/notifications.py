from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QMessageBox, QWidget


class NotificationService(Protocol):
    """Small boundary around user notifications."""

    def information(self, title: str, message: str) -> None: ...
    def warning(self, title: str, message: str) -> None: ...
    def error(self, title: str, message: str) -> None: ...
    def confirmation(self, title: str, message: str) -> bool: ...


class QtNotificationService:
    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent

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
