from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from app.models import AppSettings
from app.services.provider_setup_wizard_service import ProviderSetupDraft, ProviderSetupWizardService


class ProviderSetupWizardDialog(QWizard):
    """Guided provider setup whose mutations require an explicit Finish action."""

    settings_selected = Signal(object)

    def __init__(
        self,
        service: ProviderSetupWizardService,
        settings_provider: Callable[[], AppSettings],
        *,
        generation_active: Callable[[], bool] | None = None,
        open_account_manager: Callable[[str], object] | None = None,
        open_offline_engines: Callable[[], object] | None = None,
        open_cost_quota: Callable[[], object] | None = None,
        project_id: int | None = None,
        scoped_characters: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings_provider = settings_provider
        self.generation_active = generation_active or (lambda: False)
        self.open_account_manager = open_account_manager
        self.open_offline_engines = open_offline_engines
        self.open_cost_quota = open_cost_quota
        self.project_id = project_id
        self.scoped_characters = max(0, int(scoped_characters))
        self._draft: ProviderSetupDraft | None = None
        self._updating = False
        self._last_refresh_message = "Cached metadata only; no provider has been contacted by this wizard."
        self.setObjectName("providerSetupWizardDialog")
        self.setWindowTitle("Provider Setup Wizard — Roadmap 2 A3")
        self.resize(900, 680)
        self.setMinimumSize(780, 600)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Apply setup choices")
        self._build_pages()
        self._initialize_from_current_settings()

    def _build_pages(self) -> None:
        self.provider_page = QWizardPage()
        self.provider_page.setTitle("1. Choose provider")
        self.provider_page.setSubTitle(
            "Choose intentionally. Opening this wizard never changes the active generation provider."
        )
        provider_layout = QVBoxLayout(self.provider_page)
        provider_form = QFormLayout()
        self.provider = QComboBox()
        for choice in self.service.provider_choices():
            self.provider.addItem(
                f"{choice.display_name} · {choice.locality.title()}",
                choice.provider_id,
            )
        self.provider.currentIndexChanged.connect(self._provider_changed)
        provider_form.addRow("Provider", self.provider)
        provider_layout.addLayout(provider_form)
        self.provider_summary = QLabel()
        self.provider_summary.setWordWrap(True)
        provider_layout.addWidget(self.provider_summary)
        provider_layout.addStretch(1)
        self.addPage(self.provider_page)

        self.account_page = QWizardPage()
        self.account_page.setTitle("2. Select account")
        self.account_page.setSubTitle(
            "Account selection is only a draft until Finish. Use Provider Accounts for explicit credential tests; catalog refresh contacts the selected provider only when you press the button."
        )
        account_layout = QVBoxLayout(self.account_page)
        account_form = QFormLayout()
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(self._account_changed)
        account_form.addRow("Named account", self.account)
        account_layout.addLayout(account_form)
        account_actions = QHBoxLayout()
        self.accounts_button = QPushButton("Open Provider Accounts / Test")
        self.accounts_button.clicked.connect(self._open_accounts)
        self.verify_button = QPushButton("Refresh provider catalog")
        self.verify_button.clicked.connect(self._refresh_provider_explicit)
        self.reload_button = QPushButton("Reload accounts / cached")
        self.reload_button.clicked.connect(self._reload_local_state)
        account_actions.addWidget(self.accounts_button)
        account_actions.addWidget(self.verify_button)
        account_actions.addWidget(self.reload_button)
        account_actions.addStretch(1)
        account_layout.addLayout(account_actions)
        self.account_summary = QLabel()
        self.account_summary.setWordWrap(True)
        account_layout.addWidget(self.account_summary)
        self.refresh_summary = QLabel(self._last_refresh_message)
        self.refresh_summary.setWordWrap(True)
        account_layout.addWidget(self.refresh_summary)
        account_layout.addStretch(1)
        self.addPage(self.account_page)

        self.voice_page = QWizardPage()
        self.voice_page.setTitle("3. Choose voice and model")
        self.voice_page.setSubTitle(
            "Cached/built-in metadata is shown first. Voice/model changes remain drafts until Finish."
        )
        voice_layout = QVBoxLayout(self.voice_page)
        voice_form = QFormLayout()
        self.voice = QComboBox()
        self.voice.setEditable(True)
        self.voice.currentTextChanged.connect(self._selection_changed)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.currentTextChanged.connect(self._selection_changed)
        self.language = QComboBox()
        self.language.setEditable(True)
        for language in ("da", "en", "de", "sv", "no"):
            self.language.addItem(language, language)
        self.language.currentTextChanged.connect(self._selection_changed)
        voice_form.addRow("Voice", self.voice)
        voice_form.addRow("Model", self.model)
        voice_form.addRow("Language", self.language)
        voice_layout.addLayout(voice_form)
        self.catalog_summary = QLabel()
        self.catalog_summary.setWordWrap(True)
        voice_layout.addWidget(self.catalog_summary)
        self.offline_button = QPushButton("Open Offline TTS Engines")
        self.offline_button.clicked.connect(self._open_offline_engines)
        voice_layout.addWidget(self.offline_button)
        voice_layout.addStretch(1)
        self.addPage(self.voice_page)

        self.review_page = QWizardPage()
        self.review_page.setTitle("4. Review and apply")
        self.review_page.setSubTitle(
            "Finish applies only the provider/account/voice/model/language choices. Preflight and Generation remain separate explicit actions."
        )
        review_layout = QVBoxLayout(self.review_page)
        self.review_summary = QLabel()
        self.review_summary.setWordWrap(True)
        review_layout.addWidget(self.review_summary)
        self.cost_summary = QLabel()
        self.cost_summary.setWordWrap(True)
        review_layout.addWidget(self.cost_summary)
        self.quota_summary = QLabel()
        self.quota_summary.setWordWrap(True)
        review_layout.addWidget(self.quota_summary)
        self.limit_summary = QLabel()
        self.limit_summary.setWordWrap(True)
        review_layout.addWidget(self.limit_summary)
        self.warning_summary = QLabel()
        self.warning_summary.setWordWrap(True)
        review_layout.addWidget(self.warning_summary)
        if self.open_cost_quota is not None:
            self.cost_button = QPushButton("Open full Cost / Quota / Limits")
            self.cost_button.clicked.connect(self.open_cost_quota)
            review_layout.addWidget(self.cost_button)
        review_layout.addStretch(1)
        self.addPage(self.review_page)

    def _initialize_from_current_settings(self) -> None:
        current = self.settings_provider()
        index = self.provider.findData(current.provider)
        if index >= 0:
            self.provider.setCurrentIndex(index)
        self._populate_accounts(
            self.service.default_profile_id(current, self.current_provider_id())
        )
        self._refresh_draft(
            voice_id=current.voice_id,
            model_id=current.model_id,
            language_code=current.language_code,
        )

    def current_provider_id(self) -> str:
        return str(self.provider.currentData() or "").strip().casefold()

    def current_profile_id(self) -> str | None:
        return str(self.account.currentData() or "").strip() or None

    def _provider_changed(self) -> None:
        if self._updating:
            return
        current = self.settings_provider()
        default_profile = self.service.default_profile_id(current, self.current_provider_id())
        self._populate_accounts(default_profile)
        same_provider = self.current_provider_id() == current.provider
        self._refresh_draft(
            voice_id=current.voice_id if same_provider else "",
            model_id=current.model_id if same_provider else "",
            language_code=current.language_code,
        )

    def _account_changed(self) -> None:
        if not self._updating:
            self._refresh_draft()

    def _selection_changed(self) -> None:
        if not self._updating:
            self._refresh_draft(
                voice_id=self.voice.currentText(),
                model_id=self.model.currentText(),
                language_code=self.language.currentText(),
                repopulate_catalog=False,
            )

    def _populate_accounts(self, selected_profile_id: str | None) -> None:
        self._updating = True
        try:
            self.account.clear()
            self.account.addItem("No named account / temporary or external credential", None)
            draft = self.service.build_draft(
                self.settings_provider(),
                provider_id=self.current_provider_id(),
                profile_id=selected_profile_id,
                voice_id="",
                model_id="",
                language_code=self.settings_provider().language_code,
                project_id=self.project_id,
                scoped_characters=self.scoped_characters,
            )
            for account in draft.accounts:
                self.account.addItem(account.label, account.profile_id)
            if selected_profile_id:
                index = self.account.findData(selected_profile_id)
                if index >= 0:
                    self.account.setCurrentIndex(index)
        finally:
            self._updating = False

    def _refresh_draft(
        self,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
        language_code: str | None = None,
        repopulate_catalog: bool = True,
    ) -> None:
        if not self.current_provider_id():
            return
        current_voice = self.voice.currentText() if voice_id is None else voice_id
        current_model = self.model.currentText() if model_id is None else model_id
        current_language = self.language.currentText() if language_code is None else language_code
        draft = self.service.build_draft(
            self.settings_provider(),
            provider_id=self.current_provider_id(),
            profile_id=self.current_profile_id(),
            voice_id=current_voice,
            model_id=current_model,
            language_code=current_language,
            project_id=self.project_id,
            scoped_characters=self.scoped_characters,
        )
        self._draft = draft
        if repopulate_catalog:
            self._updating = True
            try:
                self._populate_editable_combo(self.voice, draft.voices, draft.settings.voice_id)
                self._populate_editable_combo(self.model, draft.models, draft.settings.model_id)
                if draft.settings.language_code:
                    self.language.setCurrentText(draft.settings.language_code)
            finally:
                self._updating = False
        self._render_draft(draft)

    @staticmethod
    def _populate_editable_combo(combo: QComboBox, choices, selected: str) -> None:
        combo.clear()
        for choice in choices:
            combo.addItem(choice.label, choice.item_id)
        if selected:
            index = combo.findData(selected)
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setEditText(selected)

    def _render_draft(self, draft: ProviderSetupDraft) -> None:
        account_text = draft.selected_profile_name or (
            "No credential required"
            if draft.credential_mode == "none"
            else "No named account selected"
        )
        self.provider_summary.setText(
            f"{draft.provider_name} · {draft.locality.title()} · credential mode: {draft.credential_mode}. "
            "No provider/account change has been applied yet."
        )
        self.account_summary.setText(
            f"Draft account: {account_text} · {len(draft.accounts)} configured account(s). "
            "Use Provider Accounts for adding/editing secrets and explicit account tests."
        )
        self.catalog_summary.setText(
            f"Capabilities: {draft.capability_text}.\n"
            f"Catalog state: {draft.catalog_state.replace('_', ' ')} · "
            f"{len(draft.voices)} voice(s) · {len(draft.models)} model(s). "
            f"{draft.catalog_message or 'Cached/built-in metadata only.'}"
        )
        self.review_summary.setText(
            f"Provider: {draft.provider_name}\n"
            f"Account: {account_text}\n"
            f"Voice: {draft.settings.voice_id or '—'}\n"
            f"Model: {draft.settings.model_id or '—'}\n"
            f"Language: {draft.settings.language_code or '—'}\n\n"
            "Preflight: NOT RUN · Generation: NOT STARTED · Smart Routing: NOT APPLIED"
        )
        self.cost_summary.setText(f"Cost: {draft.cost_text}")
        self.quota_summary.setText(f"Quota: {draft.quota_text}")
        self.limit_summary.setText(f"Request limit: {draft.request_limit_text}")
        messages = [
            *(f"Warning: {item}" for item in draft.warnings),
            *(f"Required: {item}" for item in draft.blockers),
        ]
        self.warning_summary.setText(
            "\n".join(messages) if messages else "Setup draft is ready to apply explicitly."
        )
        self.offline_button.setVisible(draft.locality == "local")
        self.button(QWizard.WizardButton.FinishButton).setEnabled(draft.can_apply and not self.generation_active())

    def _reload_local_state(self) -> None:
        profile_id = self.current_profile_id()
        self._populate_accounts(profile_id)
        self._refresh_draft(
            voice_id=self.voice.currentText(),
            model_id=self.model.currentText(),
            language_code=self.language.currentText(),
        )

    def _open_accounts(self) -> None:
        if self.open_account_manager is not None:
            self.open_account_manager(self.current_provider_id())

    def _open_offline_engines(self) -> None:
        if self.open_offline_engines is not None:
            self.open_offline_engines()

    def _refresh_provider_explicit(self) -> None:
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Generation active",
                "Stop the active generation run before verifying or refreshing provider setup metadata.",
            )
            return
        if QMessageBox.question(
            self,
            "Refresh selected provider catalog?",
            "This explicit action may contact only the selected provider/account and refresh its catalog metadata. Credential tests remain in Provider Accounts. It will not run Preflight, switch the active generation provider, or start generation. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        source = self.service.refresh_provider_explicit(
            self.settings_provider(),
            provider_id=self.current_provider_id(),
            profile_id=self.current_profile_id(),
        )
        self._last_refresh_message = (
            f"Explicit provider refresh: {source.state.replace('_', ' ')} · "
            f"{source.message or 'Provider metadata refreshed.'}"
        )
        self.refresh_summary.setText(self._last_refresh_message)
        if source.state == "error":
            QMessageBox.warning(self, "Provider setup", source.message or "Provider refresh failed.")
        elif source.state == "account_required":
            QMessageBox.information(self, "Provider setup", source.message)
        self._refresh_draft(
            voice_id=self.voice.currentText(),
            model_id=self.model.currentText(),
            language_code=self.language.currentText(),
        )

    def initializePage(self, page_id: int) -> None:
        self._refresh_draft(
            voice_id=self.voice.currentText(),
            model_id=self.model.currentText(),
            language_code=self.language.currentText(),
        )
        super().initializePage(page_id)

    def accept(self) -> None:
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Generation active",
                "Stop the active generation run before applying provider setup choices.",
            )
            return
        try:
            settings = self.service.final_settings(
                self.settings_provider(),
                provider_id=self.current_provider_id(),
                profile_id=self.current_profile_id(),
                voice_id=self.voice.currentText(),
                model_id=self.model.currentText(),
                language_code=self.language.currentText(),
            )
        except ValueError as exc:
            QMessageBox.information(self, "Provider setup is incomplete", str(exc))
            return
        if QMessageBox.question(
            self,
            "Apply provider setup choices?",
            (
                f"Apply provider={settings.provider}, account={self.current_profile_id() or 'none'}, "
                f"voice={settings.voice_id or 'none'}, model={settings.model_id or 'none'}?\n\n"
                "This will NOT run Preflight or start/restart generation."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.settings_selected.emit(settings)
        super().accept()
