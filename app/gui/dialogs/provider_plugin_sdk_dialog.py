from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.provider_plugin import ProviderPluginCandidate
from app.services.provider_plugin_sdk_service import ProviderPluginSDKService


class ProviderPluginSDKDialog(QDialog):
    """Explicit session-only provider plugin discovery and activation UI."""

    registryChanged = Signal(str, str)

    def __init__(
        self,
        service: ProviderPluginSDKService,
        *,
        generation_active: Callable[[], bool],
        active_provider_id: Callable[[], str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.generation_active = generation_active
        self.active_provider_id = active_provider_id
        self.candidates: tuple[ProviderPluginCandidate, ...] = ()
        self.setWindowTitle("Provider Plugins / SDK")
        self.resize(980, 560)

        layout = QVBoxLayout(self)
        warning = QLabel(
            "Provider plugins are third-party Python code. Scan only reads "
            "plugin.json and hashes; code executes only after you explicitly "
            "activate a plugin for this session."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        path_row = QHBoxLayout()
        self.root = QLineEdit(str(service.plugin_root))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_root)
        scan = QPushButton("Scan")
        scan.clicked.connect(self.scan)
        path_row.addWidget(QLabel("Plugin folder"))
        path_row.addWidget(self.root, 1)
        path_row.addWidget(browse)
        path_row.addWidget(scan)
        layout.addLayout(path_row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Plugin",
                "Provider",
                "Display name",
                "SDK",
                "State",
                "Fingerprint",
                "Message",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.update_actions)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.activate_button = QPushButton("Activate for this session")
        self.activate_button.clicked.connect(self.activate_selected)
        self.deactivate_button = QPushButton("Deactivate")
        self.deactivate_button.clicked.connect(self.deactivate_selected)
        self.template_button = QPushButton("Create starter plugin…")
        self.template_button.clicked.connect(self.create_template)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(self.activate_button)
        actions.addWidget(self.deactivate_button)
        actions.addWidget(self.template_button)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)

        self.service.ensure_directories()
        self.scan()

    def browse_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select provider plugin folder",
            self.root.text(),
        )
        if selected:
            self.root.setText(selected)
            self.scan()

    def scan(self) -> None:
        self.candidates = self.service.discover(Path(self.root.text().strip()))
        self.table.setRowCount(len(self.candidates))
        for row, candidate in enumerate(self.candidates):
            descriptor = candidate.descriptor
            values = [
                candidate.plugin_id,
                candidate.provider_id or "—",
                descriptor.display_name if descriptor else "—",
                str(descriptor.sdk_api_version) if descriptor else "—",
                candidate.state.title(),
                descriptor.fingerprint[:16] if descriptor else "—",
                candidate.message,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if descriptor:
                    item.setToolTip(descriptor.fingerprint)
                self.table.setItem(row, column, item)
        if self.candidates:
            self.table.selectRow(0)
        self.update_actions()

    def selected_candidate(self) -> ProviderPluginCandidate | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.candidates):
            return None
        return self.candidates[row]

    def update_actions(self) -> None:
        candidate = self.selected_candidate()
        self.activate_button.setEnabled(
            candidate is not None and candidate.state == "compatible"
        )
        self.deactivate_button.setEnabled(
            candidate is not None and candidate.state == "active"
        )

    def activate_selected(self) -> None:
        candidate = self.selected_candidate()
        if candidate is None or candidate.descriptor is None:
            return
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Provider Plugins",
                "Stop active generation before activating a provider plugin.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "Activate third-party Python code?",
            f"Activate {candidate.descriptor.display_name} for this S-Talking "
            "session?\n\nThe plugin Python module will execute with the same OS "
            "permissions as S-Talking. Activation is not persisted for automatic "
            "startup.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            activation = self.service.activate(
                candidate,
                approved=True,
                generation_active=False,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Provider Plugins", str(exc))
            return
        self.registryChanged.emit("activated", activation.provider_id)
        self.scan()

    def deactivate_selected(self) -> None:
        candidate = self.selected_candidate()
        if candidate is None or candidate.descriptor is None:
            return
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Provider Plugins",
                "Stop active generation before deactivating a provider plugin.",
            )
            return
        if self.active_provider_id() == candidate.provider_id:
            QMessageBox.warning(
                self,
                "Provider Plugins",
                "Select another provider before deactivating this plugin.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Deactivate provider plugin?",
            f"Deactivate {candidate.descriptor.display_name} for this session?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.deactivate(
                candidate.provider_id,
                approved=True,
                active_provider_id=self.active_provider_id(),
                generation_active=False,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Provider Plugins", str(exc))
            return
        self.registryChanged.emit("deactivated", candidate.provider_id)
        self.scan()

    def create_template(self) -> None:
        destination = QFileDialog.getExistingDirectory(
            self,
            "Select empty starter-plugin folder",
        )
        if not destination:
            return
        folder = Path(destination)
        provider_id = (
            folder.name.strip().lower().replace("-", "_").replace(" ", "_")
        )
        display_name = (
            folder.name.replace("_", " ").replace("-", " ").strip().title()
        )
        try:
            created = self.service.scaffold(
                folder,
                provider_id=provider_id,
                display_name=display_name,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Provider Plugins", str(exc))
            return
        QMessageBox.information(
            self,
            "Provider Plugins",
            f"Starter plugin created in:\n{created}",
        )
        self.root.setText(str(created.parent))
        self.scan()
