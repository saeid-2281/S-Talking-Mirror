from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import AppSettings
from app.services.provider_catalog_service import ProviderCatalogService, ProviderCapabilityCard
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace


class QuickSetupDialog(QDialog):
    STEP_TITLES = ("Welcome", "Provider", "Model", "Voice", "Language", "Finish")

    def __init__(
        self,
        provider_catalog: ProviderCatalogService,
        settings: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider_catalog = provider_catalog
        self.settings = settings
        self.setObjectName("quickSetupDialog")
        self.setWindowTitle("Quick Setup")
        self.resize(820, 600)
        self.setMinimumSize(620, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.workspace = DialogWorkspace(
            "Quick setup",
            "Choose a provider, model, voice and default language in a short guided workflow.",
            icon_name="settings",
            parent=self,
        )
        root.addWidget(self.workspace)

        progress_card = QFrame()
        progress_card.setObjectName("setupProgressCard")
        progress_layout = QHBoxLayout(progress_card)
        progress_layout.setContentsMargins(12, 8, 12, 8)
        progress_layout.setSpacing(10)
        self.progress_label = QLabel("Step 1 of 6 · Welcome")
        self.progress_label.setObjectName("setupProgressLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("setupProgressBar")
        self.progress_bar.setRange(1, len(self.STEP_TITLES))
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar, 1)
        self.workspace.add_body_widget(progress_card)

        workflow = QFrame()
        workflow.setObjectName("setupWorkflow")
        workflow_layout = QHBoxLayout(workflow)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        workflow_layout.setSpacing(10)

        self.step_rail = QFrame()
        self.step_rail.setObjectName("setupStepRail")
        rail_layout = QVBoxLayout(self.step_rail)
        rail_layout.setContentsMargins(10, 10, 10, 10)
        rail_layout.setSpacing(4)
        self.step_labels: list[QLabel] = []
        for number, title in enumerate(self.STEP_TITLES, start=1):
            label = QLabel(f"{number}. {title}")
            label.setObjectName("setupStepLabel")
            label.setProperty("active", False)
            label.setMinimumHeight(30)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.step_labels.append(label)
            rail_layout.addWidget(label)
        rail_layout.addStretch(1)
        self.step_rail.setFixedWidth(165)
        workflow_layout.addWidget(self.step_rail)

        self.stack = QStackedWidget()
        self.stack.setObjectName("setupStack")
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workflow_layout.addWidget(self.stack, 1)
        self.workspace.add_body_widget(workflow, 1)

        self.provider = QComboBox()
        self.provider.setObjectName("setupProvider")
        self.model = QComboBox()
        self.model.setObjectName("setupModel")
        self.voice = QComboBox()
        self.voice.setObjectName("setupVoice")
        self.language = QComboBox()
        self.language.setObjectName("setupLanguage")
        self.language.addItems(["da", "en", "de", "fr", "es", "sv", "no"])
        self.cards: list[ProviderCapabilityCard] = self.provider_catalog.cards(settings)
        self._build_pages()

        self.skip = QPushButton("Cancel setup")
        self.skip.setObjectName("setupCancelAction")
        self.back = QPushButton("Back")
        self.back.setObjectName("setupBackAction")
        self.next = QPushButton("Next")
        self.next.setObjectName("dialogPrimaryAction")
        self.finish = QPushButton("Save defaults")
        self.finish.setObjectName("dialogPrimaryAction")
        self.back.clicked.connect(self.previous_page)
        self.next.clicked.connect(self.next_page)
        self.skip.clicked.connect(self.reject)
        self.finish.clicked.connect(self.accept)
        self.workspace.add_footer_widget(self.skip)
        self.workspace.add_footer_stretch()
        for button in (self.back, self.next, self.finish):
            self.workspace.add_footer_widget(button)

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
        self.stack.addWidget(
            self._page(
                "Welcome",
                "This guided setup stores sensible global defaults. Individual projects can still override them.",
                tone="info",
            )
        )

        provider_page = QWidget()
        provider_page.setObjectName("setupPage")
        provider_layout = QVBoxLayout(provider_page)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.setSpacing(10)
        provider_section = DialogSection(
            "Choose provider",
            "Availability and setup state come from the provider capability catalog; no unsupported claims are inferred.",
        )
        provider_section.add_widget(self.provider)
        for card in self.cards:
            self.provider.addItem(card.display_name, card.provider_id)
        self.provider_summary = QLabel("")
        self.provider_summary.setObjectName("setupProviderSummary")
        self.provider_summary.setWordWrap(True)
        provider_section.add_widget(self.provider_summary)
        provider_layout.addWidget(provider_section)
        provider_layout.addStretch(1)
        self.stack.addWidget(provider_page)

        self.stack.addWidget(
            self._form_page(
                "Choose model",
                "Select a model available for the active provider. The list updates when the provider changes.",
                self.model,
            )
        )
        self.stack.addWidget(
            self._form_page(
                "Choose voice",
                "Choose the default voice. Project and row-level voice settings can override this later.",
                self.voice,
            )
        )
        self.stack.addWidget(
            self._form_page(
                "Default source language",
                "The language helps provider requests and voice browsing use the right defaults.",
                self.language,
            )
        )
        self.stack.addWidget(
            self._page(
                "Ready to save",
                "The selected defaults will be stored globally. Existing projects remain unchanged until their settings are edited.",
                tone="success",
            )
        )

    def _form_page(self, title: str, message: str, widget: QWidget) -> QWidget:
        page = QWidget()
        page.setObjectName("setupPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        section = DialogSection(title, message)
        section.add_widget(widget)
        layout.addWidget(section)
        layout.addStretch(1)
        return page

    def _page(self, title: str, message: str, *, tone: str) -> QWidget:
        page = QWidget()
        page.setObjectName("setupPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        status = DialogStatusCard(title, message, tone=tone)
        status.setMinimumHeight(140)
        layout.addWidget(status)
        layout.addStretch(1)
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
        card = next((item for item in self.cards if item.provider_id == provider_id), None)
        if card is not None and hasattr(self, "provider_summary"):
            badges = " · ".join(card.badges) if card.badges else "No capability badges"
            self.provider_summary.setText(f"{card.setup_state} · {badges}")

    def _update_buttons(self) -> None:
        index = self.stack.currentIndex()
        total = self.stack.count()
        self.back.setEnabled(index > 0)
        self.next.setVisible(index < total - 1)
        self.finish.setVisible(index == total - 1)
        self.progress_bar.setValue(index + 1)
        self.progress_label.setText(f"Step {index + 1} of {total} · {self.STEP_TITLES[index]}")
        for label_index, label in enumerate(self.step_labels):
            label.setProperty("active", label_index == index)
            label.setProperty("complete", label_index < index)
            label.style().unpolish(label)
            label.style().polish(label)
