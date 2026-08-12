from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    """Cached-first discovery with explicit final selection authority."""

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
        self.setWindowTitle("Voice & Model Discovery")
        self.resize(1180, 760)
        self._build_ui()
        self.reload_cached()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Voice & Model Discovery")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Explore cached account-scoped metadata and explicitly review one selection. "
            "Opening or filtering never contacts a provider, runs Preflight, starts generation, "
            "or applies Smart Routing."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.current_setup = QLabel()
        self.current_setup.setObjectName("voiceModelDiscoveryCurrentSetup")
        self.current_setup.setWordWrap(True)
        root.addWidget(self.current_setup)

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
        self.search.setPlaceholderText("Search provider, account, voice, model, language, label…")
        filters.addWidget(self.provider)
        filters.addWidget(self.kind)
        filters.addWidget(self.language)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)

        quick = QHBoxLayout()
        self.current_provider_only = QCheckBox("Current provider")
        self.current_language_only = QCheckBox("Current language")
        self.favorites_only = QCheckBox("Favorite voices")
        self.compatible_only = QCheckBox("Known compatible only")
        self.reset_filters_button = QPushButton("Reset filters")
        for widget in (
            self.current_provider_only,
            self.current_language_only,
            self.favorites_only,
            self.compatible_only,
        ):
            quick.addWidget(widget)
        quick.addStretch(1)
        quick.addWidget(self.reset_filters_button)
        root.addLayout(quick)

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

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Provider", "Name", "ID", "Language", "Profile", "Source", "Max text", "Cost"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.selection_detail = QLabel("Select a voice or model to review what would change.")
        self.selection_detail.setObjectName("voiceModelDiscoverySelectionReview")
        self.selection_detail.setWordWrap(True)
        root.addWidget(self.selection_detail)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.use_button = QPushButton("Review & use selection")
        self.use_button.setEnabled(False)
        buttons.addButton(self.use_button, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.provider.currentIndexChanged.connect(self._filters_changed)
        self.kind.currentIndexChanged.connect(self._filters_changed)
        self.language.currentIndexChanged.connect(self._filters_changed)
        self.search.textChanged.connect(self._filters_changed)
        self.current_provider_only.toggled.connect(self._filters_changed)
        self.current_language_only.toggled.connect(self._filters_changed)
        self.favorites_only.toggled.connect(self._filters_changed)
        self.compatible_only.toggled.connect(self._filters_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.use_selection())
        self.reload_button.clicked.connect(self.reload_cached)
        self.refresh_button.clicked.connect(self.refresh_selected_provider)
        self.use_button.clicked.connect(self.use_selection)
        self.accounts_button.clicked.connect(self._open_accounts)
        self.reset_filters_button.clicked.connect(self.reset_filters)

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
        self._update_current_setup()
        self._render()

    def refresh_selected_provider(self) -> None:
        provider_id = self.provider.currentData()
        if not provider_id:
            QMessageBox.information(
                self,
                "Voice & Model Discovery",
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

    def reset_filters(self) -> None:
        self.provider.setCurrentIndex(0)
        self.kind.setCurrentIndex(0)
        self.language.setCurrentIndex(0)
        self.search.clear()
        self.current_provider_only.setChecked(False)
        self.current_language_only.setChecked(False)
        self.favorites_only.setChecked(False)
        self.compatible_only.setChecked(False)
        self._render()

    def _filters_changed(self, *_args) -> None:
        self._render()

    def _update_current_setup(self) -> None:
        settings = self.settings_provider()
        self.current_setup.setText(
            f"Current setup · Provider: {settings.provider} · "
            f"Account: {settings.active_api_profile_id or 'no named account'} · "
            f"Voice: {settings.voice_id or '—'} · Model: {settings.model_id or '—'} · "
            f"Language: {settings.language_code or '—'}\n"
            "Discovery remains read-only until Review & use selection is explicitly confirmed."
        )

    def _render(self) -> None:
        if self.catalog is None:
            self.visible_items = ()
            self.table.setRowCount(0)
            return
        settings = self.settings_provider()
        self.visible_items = self.service.discovery_items(
            self.catalog,
            settings,
            query=self.search.text(),
            provider_id=self.provider.currentData(),
            kind=self.kind.currentData(),
            language=self.language.currentData(),
            current_provider_only=self.current_provider_only.isChecked(),
            current_language_only=self.current_language_only.isChecked(),
            favorites_only=self.favorites_only.isChecked(),
            compatible_only=self.compatible_only.isChecked(),
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
                f"{item.maximum_text_length:,}" if item.maximum_text_length else "—",
                f"×{item.cost_factor:g}" if item.cost_factor is not None else "—",
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
            f"{self.catalog.model_count:,} models · {self.catalog.provider_count:,} providers\n"
            f"Cached-first sources: {states}"
        )
        self._selection_changed()

    def selected_item(self) -> UnifiedCatalogItem | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_items):
            return None
        return self.visible_items[row]

    def _selection_changed(self) -> None:
        item = self.selected_item()
        if item is None:
            self.use_button.setEnabled(False)
            self.selection_detail.setText("Select a voice or model to review what would change.")
            return
        review = self.service.selection_review(self.settings_provider(), item, catalog=self.catalog)
        self.use_button.setEnabled(review.can_apply and not self.generation_active())
        compatible = ", ".join(item.compatible_model_ids) or "not declared"
        self.selection_detail.setText(
            f"{item.provider_name} · {item.kind} · {item.name} · "
            f"language {item.language_text or 'not specified'} · source {item.source_state.replace('_', ' ')}\n"
            f"Compatibility with current counterpart: {review.compatibility} · "
            f"declared compatible models: {compatible}\n"
            f"Would change: {review.change_text}\n"
            f"Review notes: {review.warning_text or 'No metadata warning.'}"
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
        review = self.service.selection_review(current, item, catalog=self.catalog)
        if not review.can_apply:
            QMessageBox.information(self, "Voice & Model Discovery", "This item does not change the current setup.")
            return
        notes = "\n".join(f"• {warning}" for warning in review.warnings)
        if notes:
            notes = f"\n\nReview notes:\n{notes}"
        answer = QMessageBox.question(
            self,
            "Apply discovered selection?",
            (
                f"{review.change_text}{notes}\n\n"
                "This explicit action applies only the reviewed selection. It will NOT refresh another "
                "provider, run Preflight, start/restart generation, or apply Smart Routing. Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        settings = self.service.selection_settings(
            current,
            item,
            allow_provider_change=review.provider_change,
            allow_profile_change=review.account_change,
        )
        self.settings_selected.emit(settings)

    def _open_accounts(self) -> None:
        if self.open_account_manager is not None:
            self.open_account_manager()
