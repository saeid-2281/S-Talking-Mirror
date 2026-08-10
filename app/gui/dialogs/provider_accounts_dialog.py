from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QComboBox,
    QDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QProgressBar,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.dialogs.provider_account_editor_dialog import ProviderAccountEditorDialog
from app.gui.icons import action_icon
from app.gui.provider_account_sync import ProviderAccountSyncController, ProviderAccountSyncResult
from app.models.api_profile import ApiProfile, ApiProfileFailoverMode, ApiProfileStatus, FailoverSettings
from app.models.domain import AppSettings
from app.models.provider_health import evaluate_provider_health
from app.services.api_profile_service import ApiProfileService
from app.services.provider_accounts_center_service import ProviderAccountsCenterService
from app.services.provider_verification_service import ProviderVerificationService
from app.services.voice_service import VoiceService


class ProviderAccountsDialog(QDialog):
    profiles_changed = Signal()

    def __init__(
        self,
        service: ApiProfileService,
        voice_service: VoiceService,
        settings_provider: Callable[[], AppSettings],
        *,
        generation_active: Callable[[], bool] | None = None,
        verification_service: ProviderVerificationService | None = None,
        provider_catalog_service=None,
        accounts_center_service: ProviderAccountsCenterService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.voice_service = voice_service
        self.settings_provider = settings_provider
        self.generation_active = generation_active or (lambda: False)
        self.verification_service = verification_service
        self.provider_catalog_service = provider_catalog_service
        self.accounts_center_service = accounts_center_service
        if self.accounts_center_service is None and provider_catalog_service is not None:
            self.accounts_center_service = ProviderAccountsCenterService(service, provider_catalog_service)
        self.sync_controller = ProviderAccountSyncController(voice_service, parent=self)
        self.sync_controller.started.connect(self._sync_started)
        self.sync_controller.completed.connect(self._sync_completed)
        self.sync_controller.failed.connect(self._sync_failed)
        self.sync_controller.cancelled.connect(self._sync_cancelled)
        self.sync_controller.busy_changed.connect(self._sync_busy_changed)
        self.setWindowTitle("Provider Accounts Center")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        self.setObjectName("providerAccountsDialog")
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("providerAccountsHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(1)
        title = QLabel("Provider accounts")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Manage every cloud-provider account from one place without changing the generation provider.")
        subtitle.setObjectName("dialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(QLabel("View"))
        self.provider = QComboBox()
        self.provider.setMinimumWidth(180)
        self._populate_provider_combo()
        header_layout.addWidget(self.provider)
        root.addWidget(header)

        self.center_summary = QFrame()
        self.center_summary.setObjectName("providerAccountsCenterSummary")
        center_summary_layout = QHBoxLayout(self.center_summary)
        center_summary_layout.setContentsMargins(10, 7, 10, 7)
        center_summary_layout.setSpacing(18)
        self.center_managed = QLabel("Managed providers: —")
        self.center_configured = QLabel("Configured: —")
        self.center_accounts = QLabel("Accounts: —")
        self.center_attention = QLabel("Needs attention: —")
        for label in (
            self.center_managed,
            self.center_configured,
            self.center_accounts,
            self.center_attention,
        ):
            label.setObjectName("providerAccountsCenterMetric")
            center_summary_layout.addWidget(label)
        center_summary_layout.addStretch()
        root.addWidget(self.center_summary)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("providerAccountsTabs")
        self.tabs.setTabPosition(QTabWidget.West)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        root.addWidget(self.tabs, 1)

        accounts_page = QWidget()
        accounts_layout = QVBoxLayout(accounts_page)
        accounts_layout.setContentsMargins(0, 8, 0, 0)
        accounts_layout.setSpacing(8)

        self.temporary_banner = QFrame()
        self.temporary_banner.setObjectName("temporaryCredentialBanner")
        temporary_layout = QHBoxLayout(self.temporary_banner)
        temporary_layout.setContentsMargins(10, 7, 10, 7)
        temporary_layout.setSpacing(8)
        self.temporary_label = QLabel("A temporary provider credential is active in the main Provider panel. Save it as a named account for testing, catalog sync and provider-specific settings.")
        self.temporary_label.setWordWrap(True)
        self.temporary_save = QPushButton("Save as account")
        self.temporary_save.setIcon(action_icon("provider.add_profile"))
        self.temporary_save.clicked.connect(self.save_temporary_as_profile)
        temporary_layout.addWidget(self.temporary_label, 1)
        temporary_layout.addWidget(self.temporary_save)
        accounts_layout.addWidget(self.temporary_banner)

        toolbar = QFrame()
        toolbar.setObjectName("providerAccountsToolbar")
        buttons = QHBoxLayout(toolbar)
        buttons.setContentsMargins(6, 4, 6, 4)
        buttons.setSpacing(6)
        actions = [
            ("Add account", "provider.add_profile", self.add_profile),
            ("Edit account", "settings", self.edit_account),
            ("Test", "provider.test_connection", self.test_selected),
            ("Set active", "provider.set_active_profile", self.set_active),
            ("Refresh", "general.refresh", self.refresh_selected_account),
        ]
        self.action_buttons: list[QPushButton] = []
        for text, icon_name, handler in actions:
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.setMinimumHeight(34)
            button.clicked.connect(handler)
            buttons.addWidget(button)
            self.action_buttons.append(button)
        buttons.addStretch()
        self.move_up_button = QPushButton("")
        self.move_up_button.setFixedSize(34, 34)
        self.move_up_button.setIcon(action_icon("provider.move_up"))
        self.move_up_button.setToolTip("Move selected profile up")
        self.move_up_button.setAccessibleName("Move selected profile up")
        self.move_up_button.clicked.connect(lambda: self.move_profile(-1))
        self.move_down_button = QPushButton("")
        self.move_down_button.setFixedSize(34, 34)
        self.move_down_button.setIcon(action_icon("provider.move_down"))
        self.move_down_button.setToolTip("Move selected profile down")
        self.move_down_button.setAccessibleName("Move selected profile down")
        self.move_down_button.clicked.connect(lambda: self.move_profile(1))
        self.more_button = QPushButton("More")
        self.more_button.setMinimumHeight(34)
        self.more_button.setIcon(action_icon("general.more"))
        self.more_menu = QMenu(self)
        self.more_actions: dict[str, QAction] = {}
        for text, icon_name, handler in [
            ("Rename", "provider.rename_profile", self.rename_profile),
            ("Replace key", "provider.replace_key", self.replace_key),
            ("Provider settings", "settings", self.edit_provider_settings),
            ("Enable/disable", "provider.toggle_enabled", self.toggle_enabled),
            ("Delete", "provider.delete_profile", self.delete_profile),
            ("Run live verification", "provider.live_verification", self.run_live_verification),
            ("Test all", "provider.test_all", self.test_all),
            ("Clear exhausted", "provider.clear_exhausted", self.clear_exhausted),
            ("Use temporary key", "provider.temporary_key", self.enter_temporary_key),
            ("Copy summary", "provider.copy_summary", self.copy_safe_summary),
        ]:
            action = self.more_menu.addAction(action_icon(icon_name), text)
            action.triggered.connect(handler)
            self.more_actions[text] = action
        self.more_button.setMenu(self.more_menu)
        buttons.addWidget(self.move_up_button)
        buttons.addWidget(self.move_down_button)
        buttons.addWidget(self.more_button)
        accounts_layout.addWidget(toolbar)

        self.accounts_summary = QFrame()
        self.accounts_summary.setObjectName("providerAccountsSummary")
        summary_layout = QHBoxLayout(self.accounts_summary)
        summary_layout.setContentsMargins(10, 6, 10, 6)
        summary_layout.setSpacing(12)
        self.accounts_count_label = QLabel("0 accounts")
        self.accounts_count_label.setObjectName("summaryStrong")
        self.active_account_label = QLabel("Active: none")
        self.active_account_label.setObjectName("summaryMuted")
        self.accounts_hint_label = QLabel("Select an account to test, activate or inspect quota.")
        self.accounts_hint_label.setObjectName("summaryMuted")
        summary_layout.addWidget(self.accounts_count_label)
        summary_layout.addWidget(self.active_account_label)
        summary_layout.addStretch()
        summary_layout.addWidget(self.accounts_hint_label)
        accounts_layout.addWidget(self.accounts_summary)

        search_row = QHBoxLayout()
        self.account_search = QLineEdit()
        self.account_search.setObjectName("providerAccountSearch")
        self.account_search.setPlaceholderText("Search accounts by name, provider, health or tier…")
        self.account_search.setClearButtonEnabled(True)
        self.account_search.textChanged.connect(self.refresh)
        search_row.addWidget(self.account_search, 1)
        accounts_layout.addLayout(search_row)

        self.account_splitter = QSplitter(Qt.Horizontal)
        self.account_splitter.setObjectName("providerAccountsSplitter")
        self.account_splitter.setChildrenCollapsible(False)

        self.stack = QStackedWidget()
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch()
        empty_title = QLabel("No saved provider accounts")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_help = QLabel("Add an account, use a temporary key, or learn how named profiles work.")
        empty_help.setAlignment(Qt.AlignCenter)
        empty_help.setWordWrap(True)
        empty_actions = QHBoxLayout()
        self.empty_add = QPushButton("Add account")
        self.empty_add.setIcon(action_icon("provider.add_profile"))
        self.empty_temp = QPushButton("Use temporary key")
        self.empty_temp.setIcon(action_icon("provider.temporary_key"))
        self.empty_learn = QPushButton("Learn how profiles work")
        self.empty_learn.setIcon(action_icon("general.info"))
        self.empty_add.clicked.connect(self.add_profile)
        self.empty_temp.clicked.connect(self.enter_temporary_key)
        self.empty_learn.clicked.connect(lambda: QMessageBox.information(self, "Provider profiles", "Profiles are named API accounts. The active enabled profile supplies the saved credential, quota snapshot, and failover order for generation."))
        for button in [self.empty_add, self.empty_temp, self.empty_learn]:
            button.setMinimumHeight(34)
            empty_actions.addWidget(button)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_help)
        empty_layout.addLayout(empty_actions)
        empty_layout.addStretch()

        self.table = QTableWidget(0, 14)
        self.table.setObjectName("providerProfilesTable")
        self.table.setHorizontalHeaderLabels([
            "Active", "Profile name", "Provider", "Masked key", "Enabled",
            "Priority", "Health", "Connection", "Tier", "Remaining quota", "Catalog", "Voices", "Models", "Last checked",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumWidth(600)
        self.table.setMinimumHeight(300)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty_state)
        self.account_splitter.addWidget(self.stack)

        self.details_panel = QFrame()
        self.details_panel.setObjectName("providerAccountDetails")
        self.details_panel.setMinimumWidth(270)
        self.details_panel.setMaximumWidth(360)
        details = QVBoxLayout(self.details_panel)
        details.setContentsMargins(14, 14, 14, 14)
        details.setSpacing(10)
        details_title = QLabel("Account details")
        details_title.setObjectName("sectionTitle")
        details.addWidget(details_title)
        details_hint = QLabel("Connection, quota and credential state for the selected account.")
        details_hint.setObjectName("dialogSubtitle")
        details_hint.setWordWrap(True)
        details.addWidget(details_hint)
        identity = QFrame()
        identity.setObjectName("providerAccountIdentity")
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(10, 10, 10, 10)
        identity_layout.setSpacing(6)
        identity_header = QHBoxLayout()
        self.details_name = QLabel("No profile selected")
        self.details_name.setObjectName("accountName")
        self.details_name.setWordWrap(True)
        self.details_badge = QLabel("No selection")
        self.details_badge.setObjectName("accountStatusBadge")
        self.details_badge.setAlignment(Qt.AlignCenter)
        identity_header.addWidget(self.details_name, 1)
        identity_header.addWidget(self.details_badge)
        identity_layout.addLayout(identity_header)
        self.details_status = QLabel("Select an account to see its connection status.")
        self.details_status.setObjectName("accountStatus")
        self.details_status.setWordWrap(True)
        self.details_status.setMinimumHeight(64)
        self.details_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        identity_layout.addWidget(self.details_status)
        self.sync_status = QLabel("Sync idle")
        self.sync_status.setObjectName("accountSyncStatus")
        self.sync_status.setWordWrap(True)
        self.sync_progress = QProgressBar()
        self.sync_progress.setObjectName("accountSyncProgress")
        self.sync_progress.setRange(0, 0)
        self.sync_progress.setTextVisible(False)
        self.sync_progress.setFixedHeight(6)
        self.sync_progress.hide()
        identity_layout.addWidget(self.sync_status)
        identity_layout.addWidget(self.sync_progress)
        details.addWidget(identity)

        quota_card = QFrame()
        quota_card.setObjectName("providerAccountQuotaCard")
        quota_layout = QVBoxLayout(quota_card)
        quota_layout.setContentsMargins(10, 10, 10, 10)
        quota_layout.setSpacing(6)
        quota_title_row = QHBoxLayout()
        quota_title = QLabel("Quota")
        quota_title.setObjectName("cardTitle")
        self.details_quota = QLabel("Unavailable")
        self.details_quota.setObjectName("cardValue")
        self.details_quota.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        quota_title_row.addWidget(quota_title)
        quota_title_row.addStretch()
        quota_title_row.addWidget(self.details_quota)
        quota_layout.addLayout(quota_title_row)
        self.quota_progress = QProgressBar()
        self.quota_progress.setObjectName("providerQuotaProgress")
        self.quota_progress.setRange(0, 100)
        self.quota_progress.setValue(0)
        self.quota_progress.setTextVisible(False)
        self.quota_progress.setFixedHeight(8)
        quota_layout.addWidget(self.quota_progress)
        details.addWidget(quota_card)

        catalog_card = QFrame()
        catalog_card.setObjectName("providerAccountCatalogCard")
        catalog_layout = QVBoxLayout(catalog_card)
        catalog_layout.setContentsMargins(10, 10, 10, 10)
        catalog_layout.setSpacing(8)
        catalog_header = QHBoxLayout()
        catalog_title = QLabel("Account catalog")
        catalog_title.setObjectName("cardTitle")
        self.details_catalog_state = QLabel("Not cached")
        self.details_catalog_state.setObjectName("catalogStateBadge")
        self.details_catalog_state.setAlignment(Qt.AlignCenter)
        catalog_header.addWidget(catalog_title)
        catalog_header.addStretch()
        catalog_header.addWidget(self.details_catalog_state)
        catalog_layout.addLayout(catalog_header)
        catalog_stats = QHBoxLayout()
        self.details_voices = QLabel("—")
        self.details_voices.setObjectName("catalogMetric")
        self.details_models = QLabel("—")
        self.details_models.setObjectName("catalogMetric")
        catalog_stats.addWidget(self._metric_widget("Voices", self.details_voices))
        catalog_stats.addWidget(self._metric_widget("TTS models", self.details_models))
        catalog_layout.addLayout(catalog_stats)
        details.addWidget(catalog_card)

        account_card = QFrame()
        account_card.setObjectName("providerAccountMetadataCard")
        account_layout = QVBoxLayout(account_card)
        account_layout.setContentsMargins(10, 10, 10, 10)
        account_layout.setSpacing(8)
        account_title = QLabel("Account metadata")
        account_title.setObjectName("cardTitle")
        account_layout.addWidget(account_title)
        self.details_form = QFormLayout()
        self.details_form.setHorizontalSpacing(12)
        self.details_form.setVerticalSpacing(8)
        self.details_tier = QLabel("—")
        self.details_health = QLabel("—")
        self.details_provider = QLabel("—")
        self.details_last_checked = QLabel("—")
        self.details_catalog_saved = QLabel("—")
        self.details_key = QLabel("—")
        self.details_configuration = QLabel("—")
        for label in [self.details_tier, self.details_health, self.details_provider, self.details_last_checked, self.details_catalog_saved, self.details_key, self.details_configuration]:
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
        self.details_form.addRow("Provider", self.details_provider)
        self.details_form.addRow("Tier", self.details_tier)
        self.details_form.addRow("Health", self.details_health)
        self.details_form.addRow("Last checked", self.details_last_checked)
        self.details_form.addRow("Catalog saved", self.details_catalog_saved)
        self.details_form.addRow("Credential", self.details_key)
        self.details_form.addRow("Provider settings", self.details_configuration)
        account_layout.addLayout(self.details_form)
        details.addWidget(account_card)
        details.addStretch()
        detail_actions = QHBoxLayout()
        self.details_test = QPushButton("Test")
        self.details_test.setIcon(action_icon("provider.test_connection"))
        self.details_test.clicked.connect(self.test_selected)
        self.details_refresh = QPushButton("Refresh catalog")
        self.details_refresh.setIcon(action_icon("general.refresh"))
        self.details_refresh.clicked.connect(self.refresh_selected_account)
        self.details_activate = QPushButton("Set active")
        self.details_activate.setIcon(action_icon("provider.set_active_profile"))
        self.details_activate.clicked.connect(self.set_active)
        self.details_cancel_sync = QPushButton("Cancel sync")
        self.details_cancel_sync.setIcon(action_icon("generation.stop"))
        self.details_cancel_sync.setEnabled(False)
        self.details_cancel_sync.clicked.connect(self.cancel_selected_sync)
        detail_actions.addWidget(self.details_test)
        detail_actions.addWidget(self.details_refresh)
        detail_actions.addWidget(self.details_cancel_sync)
        detail_actions.addWidget(self.details_activate)
        details.addLayout(detail_actions)
        self.account_splitter.addWidget(self.details_panel)
        self.account_splitter.setStretchFactor(0, 1)
        self.account_splitter.setStretchFactor(1, 0)
        self.account_splitter.setSizes([700, 300])
        accounts_layout.addWidget(self.account_splitter, 1)
        self.tabs.addTab(accounts_page, action_icon("provider.accounts"), "Accounts")

        failover_page = QWidget()
        failover_root = QVBoxLayout(failover_page)
        failover_root.setContentsMargins(16, 16, 16, 16)
        failover_root.setSpacing(12)
        intro = QLabel("Choose how S Talking should continue when the active account cannot complete the current batch.")
        intro.setWordWrap(True)
        failover_root.addWidget(intro)
        failover_form = QFormLayout()
        failover_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        failover_form.setHorizontalSpacing(16)
        failover_form.setVerticalSpacing(10)
        self.failover_mode = QComboBox()
        self.failover_mode.addItem("Never switch automatically", ApiProfileFailoverMode.NEVER)
        self.failover_mode.addItem("Pause and ask", ApiProfileFailoverMode.PAUSE)
        self.failover_mode.addItem("Switch automatically", ApiProfileFailoverMode.AUTO)
        self.max_switches = QSpinBox()
        self.max_switches.setRange(0, 20)
        self.sequence_mode = QComboBox()
        self.sequence_mode.addItem("Active profile only", "active_only")
        self.sequence_mode.addItem("Active profile then backups", "active_then_backups")
        self.sequence_mode.addItem("Manually ordered profile sequence", "manual")
        self.allow_unknown_quota = QCheckBox("Allow unknown quota with explicit override")
        failover_form.addRow("Mode", self.failover_mode)
        failover_form.addRow("Maximum switches", self.max_switches)
        failover_form.addRow("Profile sequence", self.sequence_mode)
        failover_form.addRow("", self.allow_unknown_quota)
        failover_root.addLayout(failover_form)
        self.preview_label = QLabel("Select Preview to see the next eligible account without changing anything.")
        self.preview_label.setObjectName("failoverPreview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setMinimumHeight(92)
        failover_root.addWidget(self.preview_label)
        failover_actions = QHBoxLayout()
        self.preview_button = QPushButton("Preview failover")
        self.preview_button.setIcon(action_icon("general.info"))
        self.preview_button.clicked.connect(self.preview_failover)
        self.save_failover_button = QPushButton("Save failover settings")
        self.save_failover_button.setIcon(action_icon("project.save"))
        self.save_failover_button.clicked.connect(self.save_failover)
        failover_actions.addWidget(self.preview_button)
        failover_actions.addStretch()
        failover_actions.addWidget(self.save_failover_button)
        failover_root.addLayout(failover_actions)
        failover_root.addStretch()
        self.tabs.addTab(failover_page, action_icon("general.warning"), "Failover")
        self.provider.currentIndexChanged.connect(self._provider_changed)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close = QPushButton("Close")
        close.setMinimumWidth(92)
        close.clicked.connect(self.accept)
        close_row.addWidget(close)
        root.addLayout(close_row)
        self.provider.currentIndexChanged.connect(self.refresh)
    def _populate_provider_combo(self) -> None:
        self.provider.clear()
        if self.provider_catalog_service is None:
            self.provider.addItem("ElevenLabs", "elevenlabs")
            return
        managed_ids = (
            self.accounts_center_service.managed_provider_ids()
            if self.accounts_center_service is not None
            else tuple(
                provider_id
                for provider_id in self.provider_catalog_service.provider_ids()
                if self.provider_catalog_service.manifest_for(provider_id).controls.api_profile
                and self.provider_catalog_service.manifest_for(provider_id).profile_management_ready
            )
        )
        self.provider.addItem("All managed providers", None)
        for provider_id in managed_ids:
            manifest = self.provider_catalog_service.manifest_for(provider_id)
            self.provider.addItem(manifest.display_name, provider_id)
        if len(managed_ids) == 0:
            self.provider.clear()
            self.provider.addItem("ElevenLabs", "elevenlabs")
            return
        current_provider = str(getattr(self.settings_provider(), "provider", "") or "")
        current_index = self.provider.findData(current_provider)
        self.provider.setCurrentIndex(current_index if current_index >= 0 else 0)

    def _selected_provider_id(self) -> str | None:
        value = self.provider.currentData()
        return str(value) if value else None

    def _provider_for_new_account(self) -> str | None:
        provider_id = self._selected_provider_id()
        if provider_id:
            return provider_id
        if self.accounts_center_service is None:
            return "elevenlabs"
        provider_ids = self.accounts_center_service.managed_provider_ids()
        labels = [self._provider_display_name(item) for item in provider_ids]
        if not labels:
            return None
        label, ok = QInputDialog.getItem(
            self,
            "Choose provider",
            "Provider for the new account",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        try:
            return provider_ids[labels.index(label)]
        except ValueError:
            return None

    def _manifest_for(self, provider_id: str):
        if self.provider_catalog_service is None:
            return None
        return self.provider_catalog_service.manifest_for(str(provider_id or "elevenlabs"))

    def _provider_display_name(self, provider_id: str) -> str:
        manifest = self._manifest_for(provider_id)
        return manifest.display_name if manifest is not None else str(provider_id).replace("_", " ").title()

    def _metadata_fields(self, provider_id: str) -> tuple[str, ...]:
        manifest = self._manifest_for(provider_id)
        return tuple(manifest.profile_metadata_fields) if manifest is not None else ()

    def _profile_secret_required(self, provider_id: str) -> bool:
        manifest = self._manifest_for(provider_id)
        return bool(manifest.profile_secret_required) if manifest is not None else True

    def _prompt_profile_metadata(
        self,
        provider_id: str,
        initial: dict[str, str] | None = None,
    ) -> dict[str, str] | None:
        fields = self._metadata_fields(provider_id)
        metadata = dict(initial or {})
        labels = {
            "region": "Region",
            "endpoint": "Endpoint (optional if region is set)",
            "project_id": "Project ID",
            "credential_reference": "Credential reference (optional; ADC is used when blank)",
            "api_endpoint": "API endpoint hostname (optional)",
            "aws_profile": "AWS profile (optional; default chain is used when blank)",
        }
        for field in fields:
            value, ok = QInputDialog.getText(
                self,
                f"{self._provider_display_name(provider_id)} settings",
                labels.get(field, field.replace("_", " ").title()),
                text=str(metadata.get(field, "")),
            )
            if not ok:
                return None
            value = value.strip()
            if value:
                metadata[field] = value
            else:
                metadata.pop(field, None)
        if "region" in fields and "endpoint" in fields and not metadata.get("region") and not metadata.get("endpoint"):
            QMessageBox.warning(
                self,
                "Provider settings",
                f"{self._provider_display_name(provider_id)} requires a region or endpoint.",
            )
            return None
        return metadata

    def _provider_changed(self, _index: int = -1) -> None:
        self.sync_controller.cancel_all()

    def edit_provider_settings(self) -> None:
        profile = self.selected_profile()
        if profile is None or not self.ensure_editable():
            return
        metadata = self._prompt_profile_metadata(profile.provider, profile.metadata)
        if metadata is None:
            return
        store = getattr(self.voice_service, "catalog_store", None)
        if store is not None:
            store.remove_profile(profile.provider, profile.profile_id)
        merged = dict(profile.metadata)
        for field in self._metadata_fields(profile.provider):
            if field in metadata:
                merged[field] = metadata[field]
            else:
                merged.pop(field, None)
        self.service.update_profile_metadata(profile.profile_id, merged)
        self._changed()

    @staticmethod
    def _metric_widget(title: str, value_label: QLabel) -> QFrame:
        metric = QFrame()
        metric.setObjectName("providerCatalogMetric")
        layout = QVBoxLayout(metric)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(2)
        value_label.setAlignment(Qt.AlignCenter)
        caption = QLabel(title)
        caption.setObjectName("summaryMuted")
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)
        layout.addWidget(caption)
        return metric

    def refresh(self) -> None:
        provider = self._selected_provider_id()
        selected = self.selected_profile()
        selected_id = selected.profile_id if selected else None
        query = self.account_search.text() if hasattr(self, "account_search") else ""
        if self.accounts_center_service is not None:
            profiles = self.accounts_center_service.profiles_for_view(provider, query)
            overview = self.accounts_center_service.overview()
            self.center_managed.setText(f"Managed providers: {overview.managed_provider_count}")
            self.center_configured.setText(f"Configured: {overview.configured_provider_count}")
            self.center_accounts.setText(f"Accounts: {overview.account_count}")
            self.center_attention.setText(f"Needs attention: {overview.attention_account_count}")
            self.center_summary.show()
        else:
            profiles = self.service.list_profiles(provider or "elevenlabs")
            needle = query.strip().casefold()
            if needle:
                profiles = [
                    profile
                    for profile in profiles
                    if needle in f"{profile.display_name} {profile.provider} {profile.status}".casefold()
                ]
            self.center_summary.hide()

        if hasattr(self, "accounts_count_label"):
            suffix = "account" if len(profiles) == 1 else "accounts"
            self.accounts_count_label.setText(f"{len(profiles)} {suffix}")
            if provider:
                active_profile = self.service.active_profile(provider)
                self.active_account_label.setText(
                    f"Active: {active_profile.display_name}" if active_profile else "Active: none"
                )
                self.accounts_hint_label.setText(
                    "Active means the account used when this provider is selected; it does not change the current generation provider."
                )
            else:
                active_provider_count = (
                    overview.active_provider_count
                    if self.accounts_center_service is not None
                    else len({profile.provider for profile in self.service.list_profiles() if profile.active})
                )
                self.active_account_label.setText(f"Active providers: {active_provider_count}")
                self.accounts_hint_label.setText(
                    "All managed providers are shown. Select an account to inspect it; activation is scoped to that account's provider."
                )

        current_settings = self.settings_provider()
        temporary_key = str(getattr(current_settings, "api_key", "") or "").strip()
        temporary_matches = provider is not None and str(getattr(current_settings, "provider", "")) == provider
        temporary_unprofiled = not getattr(current_settings, "active_api_profile_id", None)
        manifest = self._manifest_for(provider) if provider else None
        temporary_allowed = bool(manifest and manifest.controls.api_key and manifest.profile_secret_required)
        show_temporary = bool(
            temporary_key
            and temporary_matches
            and temporary_unprofiled
            and temporary_allowed
        )
        self.temporary_banner.setVisible(show_temporary)
        self.temporary_save.setEnabled(show_temporary)

        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            snapshot = self._catalog_snapshot(profile)
            health = evaluate_provider_health(profile, snapshot)
            values = [
                "Yes" if profile.active else "",
                profile.display_name,
                self._provider_display_name(profile.provider),
                profile.masked_key,
                "Yes" if profile.enabled else "No",
                profile.priority,
                health.label,
                self._status_label(profile),
                profile.account_tier or snapshot.account_tier or "—",
                f"{profile.remaining_characters:,}" if profile.remaining_characters is not None else (
                    f"{snapshot.remaining_characters:,}" if snapshot.remaining_characters is not None else "—"
                ),
                snapshot.state_label,
                snapshot.voice_count if snapshot.exists else "—",
                snapshot.model_count if snapshot.exists else "—",
                profile.last_checked_at or "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, profile.profile_id)
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
            if profile.profile_id == selected_id:
                self.table.selectRow(row)

        if profiles and self.table.currentRow() < 0:
            active_row = next((row for row, profile in enumerate(profiles) if profile.active), 0)
            self.table.selectRow(active_row)

        self.stack.setCurrentWidget(self.empty_state if not profiles else self.table)
        if provider:
            settings = self.service.failover_settings(provider)
            self._set_combo(self.failover_mode, settings.mode)
            self.max_switches.setValue(settings.max_switches_per_run)
            self._set_combo(self.sequence_mode, settings.sequence_mode)
            self.allow_unknown_quota.setChecked(settings.allow_unknown_quota_override)
            manifest = self._manifest_for(provider)
            self.tabs.setTabEnabled(1, bool(manifest and manifest.controls.account_failover))
        else:
            self.tabs.setTabEnabled(1, False)
            if self.tabs.currentIndex() == 1:
                self.tabs.setCurrentIndex(0)
        self._selection_changed()

    def _settings_for_profile(self, profile: ApiProfile) -> AppSettings:
        base = self.settings_provider().model_copy(update={"provider": profile.provider})
        return self.service.apply_profile(base, profile.profile_id)

    def _catalog_snapshot(self, profile: ApiProfile):
        store = getattr(self.voice_service, "catalog_store", None)
        if store is None or not profile.credential_ready:
            from app.services.provider_account_catalog_store import ProviderCatalogSnapshotInfo

            return ProviderCatalogSnapshotInfo(False, False)
        return store.inspect(self._settings_for_profile(profile))

    def _select_profile_id(self, profile_id: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and str(item.data(Qt.UserRole)) == profile_id:
                self.table.selectRow(row)
                return

    def selected_profile(self) -> ApiProfile | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        try:
            return self.service.get_profile(str(item.data(Qt.UserRole)))
        except ValueError:
            return None

    def ensure_editable(self) -> bool:
        if self.generation_active():
            QMessageBox.warning(self, "Provider accounts", "Profile changes are blocked while generation is running.")
            return False
        return True

    def save_temporary_as_profile(self) -> None:
        if not self.ensure_editable():
            return
        key = str(getattr(self.settings_provider(), "api_key", "") or "").strip()
        if not key:
            QMessageBox.information(self, "Provider accounts", "No temporary API key is currently available.")
            return
        provider = self._selected_provider_id() or str(getattr(self.settings_provider(), "provider", "") or "elevenlabs")
        name, ok = QInputDialog.getText(self, "Save temporary key", "Account name", text=f"My {self._provider_display_name(provider)} account")
        if not ok or not name.strip():
            return
        metadata = self._prompt_profile_metadata(provider)
        if metadata is None:
            return
        try:
            self.service.create_profile(
                name.strip(),
                provider=provider,
                api_key=key,
                active=not self.service.list_profiles(provider),
                metadata=metadata,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Provider accounts", str(exc))
            return
        self._changed()

    def add_profile(self) -> None:
        if not self.ensure_editable():
            return
        provider = self._provider_for_new_account()
        if provider is None:
            return
        manifest = self._manifest_for(provider)
        if manifest is None:
            QMessageBox.warning(self, "Provider accounts", "Provider account metadata is unavailable.")
            return
        editor = ProviderAccountEditorDialog(manifest, parent=self)
        if editor.exec() != QDialog.Accepted:
            return
        values = editor.values()
        try:
            profile = self.service.create_profile(
                values.display_name,
                provider=provider,
                api_key=values.api_key,
                active=not self.service.list_profiles(provider),
                metadata=values.metadata,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Provider accounts", str(exc))
            return
        self.provider.setCurrentIndex(self.provider.findData(provider))
        self._changed()
        self._select_profile_id(profile.profile_id)

    def edit_account(self) -> None:
        profile = self.selected_profile()
        if profile is None or not self.ensure_editable():
            return
        manifest = self._manifest_for(profile.provider)
        if manifest is None:
            return
        editor = ProviderAccountEditorDialog(manifest, profile=profile, parent=self)
        if editor.exec() != QDialog.Accepted:
            return
        values = editor.values()
        updated = self.service.get_profile(profile.profile_id)
        updated.display_name = values.display_name
        merged_metadata = dict(updated.metadata)
        for field in manifest.profile_metadata_fields:
            value = values.metadata.get(field)
            if value:
                merged_metadata[field] = value
            else:
                merged_metadata.pop(field, None)
        updated.metadata = merged_metadata
        store = getattr(self.voice_service, "catalog_store", None)
        if store is not None:
            store.remove_profile(profile.provider, profile.profile_id)
        try:
            self.service.update_profile(updated, api_key=values.api_key)
        except ValueError as exc:
            QMessageBox.warning(self, "Provider accounts", str(exc))
            return
        self._changed()
        self._select_profile_id(profile.profile_id)

    def rename_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or not self.ensure_editable():
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "Profile name", text=profile.display_name)
        if ok:
            try:
                self.service.rename_profile(profile.profile_id, name)
                self._changed()
            except ValueError as exc:
                QMessageBox.warning(self, "Provider accounts", str(exc))

    def replace_key(self) -> None:
        profile = self.selected_profile()
        if not profile or not self.ensure_editable():
            return
        key, ok = QInputDialog.getText(self, "Replace key", "New API key", QLineEdit.Password)
        if ok:
            store = getattr(self.voice_service, "catalog_store", None)
            if store is not None:
                store.remove_profile(profile.provider, profile.profile_id)
            self.service.replace_key(profile.profile_id, key)
            self._changed()

    def delete_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or not self.ensure_editable():
            return
        if QMessageBox.question(self, "Delete profile", f"Delete '{profile.display_name}' and remove its stored credential?") == QMessageBox.Yes:
            store = getattr(self.voice_service, "catalog_store", None)
            if store is not None:
                store.remove_profile(profile.provider, profile.profile_id)
            self.service.remove_profile(profile.profile_id)
            self._changed()

    def toggle_enabled(self) -> None:
        profile = self.selected_profile()
        if profile and self.ensure_editable():
            self.service.set_enabled(profile.profile_id, not profile.enabled)
            self._changed()

    def move_profile(self, direction: int) -> None:
        profile = self.selected_profile()
        if profile and self.ensure_editable():
            self.service.move_profile(profile.profile_id, direction)
            self._changed()

    def set_active(self) -> None:
        profile = self.selected_profile()
        if profile is None or not self.ensure_editable():
            return
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Provider accounts",
                "The active account cannot be changed while generation is running.",
            )
            return
        self.service.set_active(profile.profile_id)
        self._changed()

    def refresh_selected_account(self) -> None:
        """Force-refresh only the selected account in the background."""
        profile = self.selected_profile()
        if profile is None:
            self.refresh()
            return
        self._test_profile(profile, force=True)

    def test_selected(self) -> None:
        profile = self.selected_profile()
        if profile:
            self._test_profile(profile, force=False)

    def cancel_selected_sync(self) -> None:
        profile = self.selected_profile()
        if profile:
            self.sync_controller.cancel(profile.profile_id)

    def run_live_verification(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        if profile.provider != "elevenlabs":
            QMessageBox.information(
                self,
                "Provider verification",
                "This legacy live verification workflow is ElevenLabs-specific. Use Test or Refresh for this provider.",
            )
            return
        if self.generation_active():
            QMessageBox.warning(self, "Provider verification", "Live verification is blocked while generation is running.")
            return
        if self.verification_service is None:
            QMessageBox.warning(self, "Provider verification", "Live verification service is unavailable.")
            return
        key = self.service.api_key_for(profile.profile_id)
        if not key:
            QMessageBox.warning(self, "Provider verification", "This profile has no saved API key.")
            return
        sample, ok = QInputDialog.getText(
            self,
            "Run live verification",
            "Short preview text",
            text="Hej, dette er en kort test.",
        )
        sample = sample.strip()
        if not ok or not sample:
            return
        if QMessageBox.question(
            self,
            "Run live verification",
            f"This will send {len(sample):,} character(s) to ElevenLabs for a minimal preview. Continue?",
        ) != QMessageBox.Yes:
            return
        settings = self.settings_provider().model_copy(update={"provider": profile.provider, "api_key": key})
        try:
            report = self.verification_service.run_elevenlabs(
                settings,
                profile_name=profile.display_name,
                sample_text=sample,
                project_name=getattr(self.parent(), "project_controller", None).project_name
                if getattr(self.parent(), "project_controller", None)
                else "default",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Provider verification", str(exc))
            return
        profile.metadata["last_verified_at"] = report.json_path.parent.name
        profile.metadata["dictionary_crud_available"] = "Yes" if report.success else "Partial"
        self.service.update_profile(profile)
        self.voice_service.invalidate_provider_cache(settings)
        self._changed()
        QMessageBox.information(self, "Provider verification", f"Verification report written to:\n{report.report_dir}")

    def test_all(self) -> None:
        started = 0
        provider = self._selected_provider_id()
        profiles = (
            self.accounts_center_service.profiles_for_view(provider)
            if self.accounts_center_service is not None
            else self.service.list_profiles(provider or "elevenlabs")
        )
        for profile in profiles:
            if self._start_profile_sync(profile, force=False, quiet=True):
                started += 1
        if started == 0:
            QMessageBox.information(
                self,
                "Provider accounts",
                "No eligible account sync was started. Accounts may already be syncing.",
            )

    def clear_exhausted(self) -> None:
        profile = self.selected_profile()
        if profile and self.ensure_editable():
            self.service.clear_exhausted_state(profile.profile_id)
            self._changed()

    def enter_temporary_key(self) -> None:
        if not self.ensure_editable():
            return
        selected = self.selected_profile()
        provider = selected.provider if selected else self._selected_provider_id()
        if provider is None:
            provider = self._provider_for_new_account()
        if provider is None:
            return
        manifest = self._manifest_for(provider)
        if manifest is not None and not (manifest.controls.api_key and manifest.profile_secret_required):
            QMessageBox.information(
                self,
                "Temporary credential",
                f"{manifest.display_name} uses named/external account credentials instead of a temporary API key.",
            )
            return
        key, ok = QInputDialog.getText(self, "Temporary credential", f"{self._provider_display_name(provider)} credential / API key", QLineEdit.Password)
        if ok and self.parent() and hasattr(self.parent(), "key"):
            if hasattr(self.parent(), "provider"):
                self.parent().provider.setCurrentText(provider)
            self.parent().key.setText(key)
            self.parent().set_provider_status("Temporary provider credential entered. It is not saved to a profile.")
            self.profiles_changed.emit()

    def copy_safe_summary(self) -> None:
        provider = self._selected_provider_id()
        if provider is None and self.accounts_center_service is not None:
            text = self.accounts_center_service.safe_inventory_summary()
        else:
            text = self.service.safe_summary(provider)
        QApplication.clipboard().setText(text)

    def save_failover(self) -> None:
        provider = self._selected_provider_id()
        if provider is None:
            return
        self.service.save_failover_settings(
            provider,
            FailoverSettings(
                mode=self.failover_mode.currentData(),
                max_switches_per_run=self.max_switches.value(),
                sequence_mode=str(self.sequence_mode.currentData()),
                manual_sequence=[profile.profile_id for profile in self.service.list_profiles(provider)],
                allow_unknown_quota_override=self.allow_unknown_quota.isChecked(),
            ),
        )
        self._changed()

    def preview_failover(self) -> None:
        provider = self._selected_provider_id()
        if provider is None:
            return
        current = self.selected_profile() or self.service.active_profile(provider)
        preview = self.service.failover_preview(
            provider=provider,
            current_profile_id=current.profile_id if current else None,
            trigger_reason="insufficient_quota",
        )
        excluded = ", ".join(f"{item['profile']} ({item['reason']})" for item in preview["excluded"]) or "None"
        self.preview_label.setText(
            f"Current: {preview['current_account']}\n"
            f"Next eligible: {preview['next_eligible_account']}\n"
            f"Reason: {preview['reason']}\n"
            f"Excluded: {excluded}"
        )

    def _start_profile_sync(
        self,
        profile: ApiProfile,
        *,
        force: bool,
        quiet: bool = False,
    ) -> bool:
        if not profile.enabled:
            profile.status = ApiProfileStatus.DISABLED
            self.service.update_profile(profile)
            self.refresh()
            return False
        if self._profile_secret_required(profile.provider):
            key = self.service.api_key_for(profile.profile_id)
            if not key:
                profile.status = ApiProfileStatus.INVALID
                profile.last_error = "Missing saved credential"
                self.service.update_profile(profile)
                self.refresh()
                return False
        settings = self._settings_for_profile(profile)
        if force:
            self.voice_service.invalidate_provider_cache(settings)
        started = self.sync_controller.start(
            profile.profile_id,
            settings,
            force_refresh=force,
        )
        if not started and not quiet:
            QMessageBox.information(
                self,
                "Provider accounts",
                f"'{profile.display_name}' is already syncing.",
            )
        return started

    def _sync_started(self, profile_id: str, request_id: int, force: bool) -> None:
        try:
            profile = self.service.get_profile(profile_id)
        except ValueError:
            return
        profile.status = ApiProfileStatus.TESTING
        profile.last_error = None
        profile.metadata["sync_request_id"] = str(request_id)
        profile.metadata["sync_mode"] = "refresh" if force else "test"
        self.service.update_profile(profile)
        self.refresh()

    def _sync_completed(self, result: ProviderAccountSyncResult) -> None:
        try:
            profile = self.service.get_profile(result.profile_id)
        except ValueError:
            return
        connection = result.connection
        capability = connection.capability
        if capability is not None:
            profile.metadata["voice_count"] = str(capability.voice_count)
            profile.metadata["tts_model_count"] = str(capability.tts_model_count)
        if result.catalog is not None:
            profile.metadata["catalog_refreshed_at"] = str(result.catalog.refreshed_at or "")
            profile.metadata["catalog_profile_id"] = profile.profile_id
        profile.metadata["last_sync_latency_ms"] = str(result.latency_ms)
        profile.metadata["last_sync_result"] = connection.status
        profile.mark_checked(
            success=connection.status == "connected",
            account_tier=capability.account_tier if capability else None,
            remaining_characters=capability.remaining_characters if capability else None,
            character_limit=capability.character_limit if capability else None,
            error=None if connection.status == "connected" else connection.message,
        )
        if connection.status == "invalid_key":
            profile.status = ApiProfileStatus.INVALID
        elif connection.status == "network_error":
            profile.status = ApiProfileStatus.UNAVAILABLE
        self.service.update_profile(profile)
        self._changed(invalidate_catalog=False)

    def _sync_failed(self, profile_id: str, request_id: int, message: str) -> None:
        try:
            profile = self.service.get_profile(profile_id)
        except ValueError:
            return
        profile.status = ApiProfileStatus.UNAVAILABLE
        profile.last_error = message
        profile.metadata["sync_request_id"] = str(request_id)
        profile.metadata["last_sync_result"] = "error"
        self.service.update_profile(profile)
        self.refresh()
        self.profiles_changed.emit()

    def _sync_cancelled(self, profile_id: str, request_id: int) -> None:
        try:
            profile = self.service.get_profile(profile_id)
        except ValueError:
            return
        if profile.status == ApiProfileStatus.TESTING:
            profile.status = ApiProfileStatus.UNCHECKED
        profile.last_error = "Sync cancelled"
        profile.metadata["sync_request_id"] = str(request_id)
        profile.metadata["last_sync_result"] = "cancelled"
        self.service.update_profile(profile)
        self.refresh()

    def _sync_busy_changed(self, profile_id: str, busy: bool) -> None:
        profile = self.selected_profile()
        if profile and profile.profile_id == profile_id:
            self.sync_progress.setVisible(busy)
            self.details_cancel_sync.setEnabled(busy)
            self.details_test.setEnabled(not busy)
            self.details_refresh.setEnabled(not busy)
            self.sync_status.setText("Syncing account catalog…" if busy else "Sync idle")

    def _test_profile(self, profile: ApiProfile, *, force: bool = False) -> None:
        """Compatibility entry point for testing or refreshing one profile.

        The historical method name is retained for callers and source-contract
        tests, but work is delegated to the non-blocking sync controller. The
        controller emits ``started`` synchronously, so processing pending UI
        events here ensures the visible TESTING state is painted before the
        background provider request continues.
        """
        if self._start_profile_sync(profile, force=force):
            QApplication.processEvents()

    def _changed(self, *, invalidate_catalog: bool = True) -> None:
        if invalidate_catalog:
            self.voice_service.invalidate_provider_cache()
        self.refresh()
        self.profiles_changed.emit()

    def _selection_changed(self) -> None:
        profile = self.selected_profile()
        has_selection = profile is not None
        for button in self.action_buttons[1:]:
            button.setEnabled(has_selection)
        provider_scoped_view = self._selected_provider_id() is not None
        row = self.table.currentRow()
        self.move_up_button.setEnabled(provider_scoped_view and has_selection and row > 0)
        self.move_down_button.setEnabled(
            provider_scoped_view and has_selection and 0 <= row < self.table.rowCount() - 1
        )
        self.more_button.setEnabled(True)
        if hasattr(self, "more_actions"):
            policy = (
                self.accounts_center_service.action_policy(profile)
                if profile is not None and self.accounts_center_service is not None
                else None
            )
            secret_required = bool(profile and self._profile_secret_required(profile.provider))
            if "Replace key" in self.more_actions:
                self.more_actions["Replace key"].setEnabled(
                    has_selection and (policy.can_replace_secret if policy else secret_required)
                )
            if "Provider settings" in self.more_actions:
                self.more_actions["Provider settings"].setEnabled(
                    has_selection and (policy.can_edit_metadata if policy else bool(profile and self._metadata_fields(profile.provider)))
                )
            if "Use temporary key" in self.more_actions:
                self.more_actions["Use temporary key"].setEnabled(
                    policy.can_use_temporary_secret if policy else secret_required
                )
            if "Run live verification" in self.more_actions:
                self.more_actions["Run live verification"].setEnabled(
                    bool(profile and profile.provider == "elevenlabs")
                )
            if "Clear exhausted" in self.more_actions:
                self.more_actions["Clear exhausted"].setEnabled(
                    bool(profile and profile.status == ApiProfileStatus.EXHAUSTED)
                )
        selected_provider = self._selected_provider_id()
        selected_manifest = self._manifest_for(selected_provider) if selected_provider else None
        temporary_available = bool(
            selected_manifest
            and selected_manifest.controls.api_key
            and selected_manifest.profile_secret_required
        )
        self.empty_temp.setVisible(temporary_available)
        self._update_details(profile)

    def _update_details(self, profile: ApiProfile | None) -> None:
        enabled = profile is not None
        busy = bool(profile and self.sync_controller.is_busy(profile.profile_id))
        self.details_test.setEnabled(enabled and not busy)
        self.details_refresh.setEnabled(enabled and not busy)
        self.details_cancel_sync.setEnabled(busy)
        self.sync_progress.setVisible(busy)
        self.sync_status.setText("Syncing account catalog…" if busy else "Sync idle")
        self.details_activate.setEnabled(enabled and not bool(profile.active) if profile else False)
        if profile is None:
            self.details_name.setText("No profile selected")
            self.details_badge.setText("No selection")
            self.details_badge.setProperty("status", "neutral")
            self.details_status.setText("Select an account to see its connection status.")
            self.details_provider.setText("—")
            self.details_tier.setText("—")
            self.details_health.setText("—")
            self.details_quota.setText("Unavailable")
            self.quota_progress.setValue(0)
            self.details_voices.setText("—")
            self.details_models.setText("—")
            self.details_catalog_state.setText("Not cached")
            self.details_catalog_state.setProperty("state", "missing")
            self.details_catalog_saved.setText("—")
            self.details_last_checked.setText("—")
            self.details_key.setText("—")
            self.details_configuration.setText("—")
            self.details_badge.style().unpolish(self.details_badge)
            self.details_badge.style().polish(self.details_badge)
            return
        self.details_name.setText(profile.display_name)
        status_label = self._status_label(profile)
        self.details_badge.setText("Active" if profile.active else status_label)
        self.details_badge.setProperty("status", self._status_property(profile))
        self.details_badge.style().unpolish(self.details_badge)
        self.details_badge.style().polish(self.details_badge)
        status = status_label
        if profile.last_error:
            status = f"{status}\n{profile.last_error}"
        self.details_status.setText(status)
        self.details_status.setToolTip(status)
        self.details_provider.setText(self._provider_display_name(profile.provider))
        self.details_tier.setText(profile.account_tier or "Unknown")
        if profile.remaining_characters is None:
            self.details_quota.setText("Unavailable")
            self.quota_progress.setValue(0)
        elif profile.character_limit:
            self.details_quota.setText(f"{profile.remaining_characters:,} / {profile.character_limit:,}")
            percent = round((profile.remaining_characters / profile.character_limit) * 100)
            self.quota_progress.setValue(max(0, min(100, percent)))
        else:
            self.details_quota.setText(f"{profile.remaining_characters:,} remaining")
            self.quota_progress.setValue(0)
        snapshot = self._catalog_snapshot(profile)
        health = evaluate_provider_health(profile, snapshot)
        health_text = health.label
        if health.quota_percent is not None:
            health_text += f" · {health.quota_percent}% quota"
        if health.latency_ms is not None:
            health_text += f" · {health.latency_ms} ms"
        self.details_health.setText(health_text)
        self.details_health.setToolTip(health.reason)
        self.details_voices.setText(str(snapshot.voice_count) if snapshot.exists else str(profile.metadata.get("voice_count", "Unknown")))
        self.details_models.setText(str(snapshot.model_count) if snapshot.exists else str(profile.metadata.get("tts_model_count", "Unknown")))
        self.details_catalog_state.setText(snapshot.state_label)
        self.details_catalog_state.setProperty(
            "state", "stale" if snapshot.stale else ("fresh" if snapshot.exists else "missing")
        )
        self.details_catalog_state.style().unpolish(self.details_catalog_state)
        self.details_catalog_state.style().polish(self.details_catalog_state)
        catalog_tip = snapshot.refreshed_at or snapshot.saved_at or "Catalog has not been refreshed for this account."
        latency = profile.metadata.get("last_sync_latency_ms")
        if latency:
            catalog_tip = f"{catalog_tip}\nLast sync latency: {latency} ms"
        self.details_catalog_state.setToolTip(catalog_tip)
        self.details_catalog_saved.setText(snapshot.saved_at or "Not cached")
        self.details_last_checked.setText(profile.last_checked_at or "Not checked")
        self.details_key.setText(profile.masked_key)
        fields = self._metadata_fields(profile.provider)
        visible_metadata = [f"{field}={profile.metadata.get(field, '—')}" for field in fields]
        self.details_configuration.setText(" · ".join(visible_metadata) if visible_metadata else "No provider-specific settings")

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self.sync_controller.cancel_all()
        super().closeEvent(event)

    @staticmethod
    def _status_property(profile: ApiProfile) -> str:
        if profile.active and profile.status == ApiProfileStatus.READY:
            return "active"
        if profile.status == ApiProfileStatus.READY:
            return "success"
        if profile.status in {ApiProfileStatus.INVALID, ApiProfileStatus.UNAVAILABLE, ApiProfileStatus.EXHAUSTED}:
            return "error"
        if profile.status == ApiProfileStatus.TESTING:
            return "info"
        if not profile.enabled or profile.status == ApiProfileStatus.DISABLED:
            return "disabled"
        return "neutral"

    @staticmethod
    def _status_label(profile: ApiProfile) -> str:
        if not profile.enabled:
            return "Disabled"
        labels = {
            ApiProfileStatus.UNCHECKED: "Not tested",
            ApiProfileStatus.TESTING: "Testing",
            ApiProfileStatus.READY: "Connected",
            ApiProfileStatus.INVALID: "Invalid key",
            ApiProfileStatus.EXHAUSTED: "Exhausted",
            ApiProfileStatus.DISABLED: "Disabled",
            ApiProfileStatus.UNAVAILABLE: "Network unavailable",
        }
        return labels.get(profile.status, str(profile.status))

    @staticmethod
    def _set_combo(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)
