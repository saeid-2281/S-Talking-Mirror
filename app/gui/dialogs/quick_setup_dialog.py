from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import AppSettings
from app.services.provider_catalog_service import ProviderCatalogService, ProviderCapabilityCard


class QuickSetupDialog(QDialog):
    def __init__(
        self,
        provider_catalog: ProviderCatalogService,
        settings: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider_catalog = provider_catalog
        self.settings = settings
        self.setWindowTitle("Quick Setup")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.provider = QComboBox()
        self.model = QComboBox()
        self.voice = QComboBox()
        self.language = QComboBox()
        self.language.addItems(["da", "en", "de", "fr", "es", "sv", "no"])
        self.cards: list[ProviderCapabilityCard] = self.provider_catalog.cards(settings)
        self._build_pages()
        buttons = QHBoxLayout()
        self.back = QPushButton("Back")
        self.next = QPushButton("Next")
        self.skip = QPushButton("Skip")
        self.finish = QPushButton("Finish")
        self.back.clicked.connect(self.previous_page)
        self.next.clicked.connect(self.next_page)
        self.skip.clicked.connect(self.reject)
        self.finish.clicked.connect(self.accept)
        for button in [self.back, self.next, self.skip, self.finish]:
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()
        self._update_buttons()

    def selected_settings(self) -> AppSettings:
        updated = self.settings
        updated.provider = self.provider.currentData() or updated.provider
        updated.model_id = self.model.currentData() or updated.model_id
        updated.voice_id = self.voice.currentData() or updated.voice_id
        updated.language_code = self.language.currentText() or updated.language_code
        return updated

    def next_page(self) -> None:
        self.stack.setCurrentIndex(min(self.stack.count() - 1, self.stack.currentIndex() + 1))
        self._update_buttons()

    def previous_page(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_buttons()

    def _build_pages(self) -> None:
        self.stack.addWidget(self._page("Welcome", "Choose a provider and make a short preview before saving defaults."))
        provider_page = QWidget()
        provider_layout = QVBoxLayout(provider_page)
        provider_layout.addWidget(QLabel("Choose provider"))
        for card in self.cards:
            self.provider.addItem(card.display_name, card.provider_id)
            provider_layout.addWidget(QLabel(f"{card.display_name}: {card.setup_state} · {', '.join(card.badges)}"))
        provider_layout.addWidget(self.provider)
        self.stack.addWidget(provider_page)
        self.stack.addWidget(self._form_page("Choose model", self.model))
        self.stack.addWidget(self._form_page("Choose voice", self.voice))
        self.stack.addWidget(self._form_page("Default source language", self.language))
        self.stack.addWidget(self._page("Finish", "Defaults are saved globally. Project settings can still override them."))

    def _form_page(self, title: str, widget: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(title))
        layout.addWidget(widget)
        layout.addStretch()
        return page

    def _page(self, title: str, message: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title)
        heading.setObjectName("title")
        layout.addWidget(heading)
        layout.addWidget(QLabel(message))
        layout.addStretch()
        return page

    def _provider_changed(self) -> None:
        provider_id = self.provider.currentData() or "mock"
        capabilities = self.provider_catalog.capabilities_for(provider_id, self.settings)
        self.model.clear()
        self.voice.clear()
        for model in getattr(capabilities, "supported_models", ()) or ():
            self.model.addItem(str(model), str(model))
        if not self.model.count():
            self.model.addItem("Default", "")
        for voice in getattr(capabilities, "supported_voices", ()) or ():
            self.voice.addItem(str(voice), str(voice))
        if not self.voice.count():
            self.voice.addItem("Configured voice", self.settings.voice_id)

    def _update_buttons(self) -> None:
        index = self.stack.currentIndex()
        self.back.setEnabled(index > 0)
        self.next.setVisible(index < self.stack.count() - 1)
        self.finish.setVisible(index == self.stack.count() - 1)
