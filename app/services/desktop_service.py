from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication


class DesktopService:
    def open_path(self, path: Path) -> None:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {target}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def open_file(self, path: Path) -> None:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(f"File does not exist: {target}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def open_in_vscode(self, path: Path) -> None:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {target}")
        subprocess.Popen(["code", str(target)])

    def copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)
