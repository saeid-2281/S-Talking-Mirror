from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

import app
from app.config.runtime import RuntimeConfig


class AboutDialog(QDialog):
    def __init__(self, runtime: RuntimeConfig, *, open_diagnostics=None, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.open_diagnostics = open_diagnostics
        self.setWindowTitle("About S Talking")
        self.setMinimumSize(520, 360)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        symbol = QLabel()
        symbol.setPixmap(self._symbol_pixmap())
        symbol.setFixedSize(72, 72)
        text = QVBoxLayout()
        title = QLabel("S Talking")
        title.setObjectName("title")
        descriptor = QLabel("AI Audio Studio")
        descriptor.setObjectName("subtitle")
        version = QLabel(f"Version {app.__version__} · {app.__release_channel__}")
        version.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.addWidget(title)
        text.addWidget(descriptor)
        text.addWidget(version)
        header.addWidget(symbol)
        header.addLayout(text, 1)
        root.addLayout(header)

        description = QLabel(
            "A calm production workspace for turning structured text into audio with "
            "project tracking, provider safety checks, reports, and repeatable batches."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        self.runtime_info = QTextEdit()
        self.runtime_info.setReadOnly(True)
        self.runtime_info.setPlainText(self._runtime_text())
        root.addWidget(self.runtime_info, 1)

        actions = QHBoxLayout()
        copy = QPushButton("Copy runtime information")
        copy.clicked.connect(self.copy_runtime_information)
        diagnostics = QPushButton("Open diagnostics")
        diagnostics.setEnabled(callable(self.open_diagnostics))
        diagnostics.clicked.connect(lambda: self.open_diagnostics() if callable(self.open_diagnostics) else None)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(copy)
        actions.addWidget(diagnostics)
        actions.addStretch()
        actions.addWidget(close)
        root.addLayout(actions)

    def copy_runtime_information(self) -> None:
        QGuiApplication.clipboard().setText(self.runtime_info.toPlainText())

    def _runtime_text(self) -> str:
        return "\n".join(
            [
                "Product: S Talking AI Audio Studio",
                f"Version: {app.__version__}",
                f"Channel: {app.__release_channel__}",
                f"Application root: {self.runtime.app_root}",
                f"Data directory: {self.runtime.data_dir}",
                f"Reports directory: {self.runtime.reports_dir}",
                f"Resource directory: {self.runtime.bundled_root}",
            ]
        )

    def _symbol_pixmap(self) -> QPixmap:
        path = self.runtime.resource_path("app", "resources", "brand", "logo-symbol.svg")
        if not path.exists():
            path = Path(__file__).resolve().parents[2] / "resources" / "brand" / "logo-symbol.svg"
        pixmap = QPixmap(72, 72)
        pixmap.fill(Qt.transparent)
        if path.exists():
            from PySide6.QtGui import QPainter

            painter = QPainter(pixmap)
            QSvgRenderer(str(path)).render(painter)
            painter.end()
        return pixmap

    @staticmethod
    def app_icon(runtime: RuntimeConfig) -> QIcon:
        icon_path = runtime.resource_path("app", "resources", "brand", "app-icon.ico")
        if icon_path.exists():
            return QIcon(str(icon_path))
        fallback = Path(__file__).resolve().parents[2] / "resources" / "brand" / "app-icon.svg"
        return QIcon(str(fallback)) if fallback.exists() else QIcon()
