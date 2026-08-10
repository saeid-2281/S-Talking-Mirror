from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models import AppSettings
from app.models.unified_voice_model_catalog import UnifiedCatalogItem, UnifiedVoiceModelCatalog
from app.services.unified_voice_model_catalog_service import UnifiedVoiceModelCatalogService


class UnifiedVoiceModelCatalogDialog(QDialog):
    """Cross-provider cached voice/model browser with explicit provider switching."""

    settings_selected = Signal(object)

    def __init__(
        self,
        service: UnifiedVoiceModelCatalogService,
        settings_provider: Callable[[], AppSettings],
        *,
        open_account_manager: Callable[[], object] | None = None,
        generation_active: Callable[[], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings_provider = settings_provider
        self.open_account_manager = open_account_manager
        self.generation_active = generation_active or (lambda: False)
        self.catalog: UnifiedVoiceModelCatalog | None = None
        self.visible_items: tuple[UnifiedCatalogItem, ...] = ()
        self.setWindowTitle("Unified Voice & Model Catalog")
        self.resize(1040, 700)
        self._build_ui()
        self.reload_cached()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Unified Voice & Model Catalog")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        root.addWidget(
            QLabel(
                "Browse account-scoped voice/model metadata across providers. "
                "Refreshing or searching never changes the generation provider."
            )
        )

        filters = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.addItem("All providers", None)
        for provider_id in self.service.providers.provider_ids():
            manifest = self.service.providers.manifest_for(provider_id)
            self.provider.addItem(manifest.display_name, provider_id)
        self.kind = QComboBox()
        self.kind.addItem("Voices & models", None)
        self.kind.addItem("Voices", "voice")
        self.kind.addItem("Models", "model")
        self.language = QComboBox()
        self.language.addItem("All languages", None)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search provider, profile, voice, model, language…")
        filters.addWidget(self.provider)
        filters.addWidget(self.kind)
        filters.addWidget(self.language)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh selected provider")
        self.accounts_button = QPushButton("Provider accounts")
        self.reload_button = QPushButton("Reload cached")
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.reload_button)
        if self.open_account_manager is not None:
            actions.addWidget(self.accounts_button)
        else:
            self.accounts_button.hide()
        actions.addStretch(1)
        root.addLayout(actions)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Provider", "Name", "ID", "Language", "Profile", "Source"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.selection_detail = QLabel("Select a voice or model to inspect it.")
        self.selection_detail.setWordWrap(True)
        root.addWidget(self.selection_detail)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.use_button = QPushButton("Use selection")
        self.use_button.setEnabled(False)
        buttons.addButton(self.use_button, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.provider.currentIndexChanged.connect(self._filters_changed)
        self.kind.currentIndexChanged.connect(self._filters_changed)
        self.language.currentIndexChanged.connect(self._filters_changed)
        self.search.textChanged.connect(self._filters_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.use_selection())
        self.reload_button.clicked.connect(self.reload_cached)
        self.refresh_button.clicked.connect(self.refresh_selected_provider)
        self.use_button.clicked.connect(self.use_selection)
        self.accounts_button.clicked.connect(self._open_accounts)

    def reload_cached(self) -> None:
        self.catalog = self.service.snapshot(self.settings_provider(), allow_stale=True)
        current_language = self.language.currentData()
        self.language.blockSignals(True)
        self.language.clear()
        self.language.addItem("All languages", None)
        for language in self.service.languages(self.catalog):
            self.language.addItem(language, language)
        if current_language:
            index = self.language.findData(current_language)
            if index >= 0:
                self.language.setCurrentIndex(index)
        self.language.blockSignals(False)
        self._render()

    def refresh_selected_provider(self) -> None:
        provider_id = self.provider.currentData()
        if not provider_id:
            QMessageBox.information(
                self,
                "Unified catalog",
                "Choose one provider before refreshing. All-provider refresh is intentionally disabled.",
            )
            return
        self.refresh_button.setEnabled(False)
        try:
            source = self.service.refresh_provider(str(provider_id), self.settings_provider())
        finally:
            self.refresh_button.setEnabled(True)
        if source.state == "error":
            QMessageBox.warning(self, "Catalog refresh", source.message or "Catalog refresh failed.")
        elif source.state == "account_required":
            QMessageBox.information(self, "Catalog refresh", source.message)
        self.reload_cached()

    def _filters_changed(self) -> None:
        self._render()

    def _render(self) -> None:
        if self.catalog is None:
            self.visible_items = ()
            self.table.setRowCount(0)
            return
        self.visible_items = self.service.filtered_items(
            self.catalog,
            query=self.search.text(),
            provider_id=self.provider.currentData(),
            kind=self.kind.currentData(),
            language=self.language.currentData(),
        )
        self.table.setRowCount(len(self.visible_items))
        for row, item in enumerate(self.visible_items):
            values = (
                item.kind.title(),
                item.provider_name,
                item.name,
                item.item_id,
                item.language_text or "—",
                item.profile_name or "—",
                item.source_state.replace("_", " ").title(),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, item.key)
                self.table.setItem(row, column, cell)
        self.table.resizeColumnsToContents()
        self.refresh_button.setEnabled(self.provider.currentData() is not None)
        states = ", ".join(
            f"{source.provider_name}: {source.state.replace('_', ' ')}"
            for source in self.catalog.sources
        )
        self.summary.setText(
            f"{len(self.visible_items):,} visible · {self.catalog.voice_count:,} voices · "
            f"{self.catalog.model_count:,} models · {self.catalog.provider_count:,} providers\n{states}"
        )
        self._selection_changed()

    def selected_item(self) -> UnifiedCatalogItem | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_items):
            return None
        return self.visible_items[row]

    def _selection_changed(self) -> None:
        item = self.selected_item()
        self.use_button.setEnabled(item is not None and not self.generation_active())
        if item is None:
            self.selection_detail.setText("Select a voice or model to inspect it.")
            return
        compatible = ", ".join(item.compatible_model_ids) or "provider catalog"
        self.selection_detail.setText(
            f"{item.provider_name} · {item.kind} · {item.name} · "
            f"language {item.language_text or 'not specified'} · compatible models: {compatible}"
        )

    def use_selection(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Generation active",
                "Stop the active generation run before changing provider, voice, or model selection.",
            )
            return
        current = self.settings_provider()
        provider_change = item.provider_id != current.provider
        profile_change = bool(
            item.profile_id and item.profile_id != current.active_api_profile_id
        )
        if provider_change or profile_change:
            changes: list[str] = []
            if provider_change:
                changes.append(f"provider {current.provider} → {item.provider_id}")
            if profile_change:
                changes.append(f"account → {item.profile_name or item.profile_id}")
            answer = QMessageBox.question(
                self,
                "Apply catalog selection?",
                f"Use this {item.kind} and explicitly apply: {', '.join(changes)}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        settings = self.service.selection_settings(
            current,
            item,
            allow_provider_change=provider_change,
            allow_profile_change=profile_change,
        )
        self.settings_selected.emit(settings)

    def _open_accounts(self) -> None:
        if self.open_account_manager is not None:
            self.open_account_manager()
