from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
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

from app.gui.icons import action_icon
from app.models.api_profile import ApiProfile, ApiProfileFailoverMode, ApiProfileStatus, FailoverSettings
from app.models.domain import AppSettings
from app.services.api_profile_service import ApiProfileService
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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.voice_service = voice_service
        self.settings_provider = settings_provider
        self.generation_active = generation_active or (lambda: False)
        self.verification_service = verification_service
        self.setWindowTitle("Provider Accounts")
        self.resize(1080, 680)
        self.setMinimumSize(820, 540)
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
        subtitle = QLabel("Manage named credentials, account status and failover order.")
        subtitle.setObjectName("dialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(QLabel("Provider"))
        self.provider = QComboBox()
        self.provider.setMinimumWidth(180)
        self.provider.addItem("ElevenLabs", "elevenlabs")
        header_layout.addWidget(self.provider)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("providerAccountsTabs")
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
        self.temporary_label = QLabel("A temporary API key is active in the main Provider panel. Save it as a named account to manage quota, testing and failover.")
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
            ("Test", "provider.test_connection", self.test_selected),
            ("Set active", "provider.set_active_profile", self.set_active),
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
        for text, icon_name, handler in [
            ("Rename", "provider.rename_profile", self.rename_profile),
            ("Replace key", "provider.replace_key", self.replace_key),
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
        self.more_button.setMenu(self.more_menu)
        buttons.addWidget(self.move_up_button)
        buttons.addWidget(self.move_down_button)
        buttons.addWidget(self.more_button)
        accounts_layout.addWidget(toolbar)

        self.account_splitter = QSplitter(Qt.Horizontal)
        self.account_splitter.setObjectName("providerAccountsSplitter")
        self.account_splitter.setChildrenCollapsible(False)

        self.stack = QStackedWidget()
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch()
        empty_title = QLabel("No saved ElevenLabs accounts")
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

        self.table = QTableWidget(0, 10)
        self.table.setObjectName("providerProfilesTable")
        self.table.setHorizontalHeaderLabels([
            "Active", "Profile name", "Provider", "Masked key", "Enabled",
            "Priority", "Connection", "Tier", "Remaining quota", "Last checked",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumWidth(560)
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
        self.details_name = QLabel("No profile selected")
        self.details_name.setObjectName("accountName")
        self.details_name.setWordWrap(True)
        self.details_status = QLabel("Select an account to see its connection status.")
        self.details_status.setObjectName("accountStatus")
        self.details_status.setWordWrap(True)
        self.details_status.setMinimumHeight(48)
        self.details_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        details.addWidget(self.details_name)
        details.addWidget(self.details_status)
        self.details_form = QFormLayout()
        self.details_form.setHorizontalSpacing(12)
        self.details_form.setVerticalSpacing(8)
        self.details_tier = QLabel("—")
        self.details_quota = QLabel("—")
        self.details_last_checked = QLabel("—")
        self.details_key = QLabel("—")
        for label in [self.details_tier, self.details_quota, self.details_last_checked, self.details_key]:
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
        self.details_form.addRow("Tier", self.details_tier)
        self.details_form.addRow("Quota", self.details_quota)
        self.details_form.addRow("Last checked", self.details_last_checked)
        self.details_form.addRow("Credential", self.details_key)
        details.addLayout(self.details_form)
        details.addStretch()
        detail_actions = QHBoxLayout()
        self.details_test = QPushButton("Test")
        self.details_test.setIcon(action_icon("provider.test_connection"))
        self.details_test.clicked.connect(self.test_selected)
        self.details_activate = QPushButton("Set active")
        self.details_activate.setIcon(action_icon("provider.set_active_profile"))
        self.details_activate.clicked.connect(self.set_active)
        detail_actions.addWidget(self.details_test)
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

        close_row = QHBoxLayout()
        close_row.addStretch()
        close = QPushButton("Close")
        close.setMinimumWidth(92)
        close.clicked.connect(self.accept)
        close_row.addWidget(close)
        root.addLayout(close_row)
        self.provider.currentIndexChanged.connect(self.refresh)
    def refresh(self) -> None:
        provider = self.provider.currentData()
        selected_id = self.selected_profile().profile_id if self.selected_profile() else None
        profiles = self.service.list_profiles(provider)
        temporary_key = str(getattr(self.settings_provider(), "api_key", "") or "").strip()
        self.temporary_banner.setVisible(bool(temporary_key))
        self.temporary_save.setEnabled(bool(temporary_key))
        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            values = [
                "Yes" if profile.active else "",
                profile.display_name,
                profile.provider,
                profile.masked_key,
                "Yes" if profile.enabled else "No",
                profile.priority,
                self._status_label(profile),
                profile.account_tier or "—",
                f"{profile.remaining_characters:,}" if profile.remaining_characters is not None else "—",
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
        settings = self.service.failover_settings(provider)
        self._set_combo(self.failover_mode, settings.mode)
        self.max_switches.setValue(settings.max_switches_per_run)
        self._set_combo(self.sequence_mode, settings.sequence_mode)
        self.allow_unknown_quota.setChecked(settings.allow_unknown_quota_override)
        self._selection_changed()

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
        name, ok = QInputDialog.getText(self, "Save temporary key", "Account name", text="My ElevenLabs account")
        if not ok or not name.strip():
            return
        try:
            self.service.create_profile(
                name.strip(),
                provider=self.provider.currentData(),
                api_key=key,
                active=not self.service.list_profiles(self.provider.currentData()),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Provider accounts", str(exc))
            return
        self._changed()

    def add_profile(self) -> None:
        if not self.ensure_editable():
            return
        name, ok = QInputDialog.getText(self, "Add profile", "Profile name")
        if not ok:
            return
        key, ok = QInputDialog.getText(self, "API key", "ElevenLabs API key", QLineEdit.Password)
        if not ok:
            return
        self.service.create_profile(name, provider=self.provider.currentData(), api_key=key, active=not self.service.list_profiles(self.provider.currentData()))
        self._changed()

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
            self.service.replace_key(profile.profile_id, key)
            self._changed()

    def delete_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or not self.ensure_editable():
            return
        if QMessageBox.question(self, "Delete profile", f"Delete '{profile.display_name}' and remove its stored credential?") == QMessageBox.Yes:
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
        if profile and self.ensure_editable():
            self.service.set_active(profile.profile_id)
            self._changed()

    def test_selected(self) -> None:
        profile = self.selected_profile()
        if profile:
            self._test_profile(profile)
            self._changed()

    def run_live_verification(self) -> None:
        profile = self.selected_profile()
        if not profile:
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
        for profile in self.service.list_profiles(self.provider.currentData()):
            self._test_profile(profile)
        self._changed()

    def clear_exhausted(self) -> None:
        profile = self.selected_profile()
        if profile and self.ensure_editable():
            self.service.clear_exhausted_state(profile.profile_id)
            self._changed()

    def enter_temporary_key(self) -> None:
        if not self.ensure_editable():
            return
        key, ok = QInputDialog.getText(self, "Temporary key", "Temporary API key", QLineEdit.Password)
        if ok and self.parent() and hasattr(self.parent(), "key"):
            self.parent().key.setText(key)
            self.parent().set_provider_status("Temporary key entered. It is not saved to a profile.")
            self.profiles_changed.emit()

    def copy_safe_summary(self) -> None:
        QApplication.clipboard().setText(self.service.safe_summary(self.provider.currentData()))

    def save_failover(self) -> None:
        self.service.save_failover_settings(
            self.provider.currentData(),
            FailoverSettings(
                mode=self.failover_mode.currentData(),
                max_switches_per_run=self.max_switches.value(),
                sequence_mode=str(self.sequence_mode.currentData()),
                manual_sequence=[profile.profile_id for profile in self.service.list_profiles(self.provider.currentData())],
                allow_unknown_quota_override=self.allow_unknown_quota.isChecked(),
            ),
        )
        self._changed()

    def preview_failover(self) -> None:
        current = self.selected_profile() or self.service.active_profile(self.provider.currentData())
        preview = self.service.failover_preview(
            provider=self.provider.currentData(),
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

    def _test_profile(self, profile: ApiProfile) -> None:
        if not profile.enabled:
            profile.status = ApiProfileStatus.DISABLED
            self.service.update_profile(profile)
            return
        key = self.service.api_key_for(profile.profile_id)
        if not key:
            profile.status = ApiProfileStatus.INVALID
            profile.last_error = "Missing saved key"
            self.service.update_profile(profile)
            return
        settings = self.settings_provider().model_copy(update={"provider": profile.provider, "api_key": key})
        result = self.voice_service.test_connection(settings)
        cap = result.capability
        profile.mark_checked(
            success=result.status == "connected",
            account_tier=cap.account_tier if cap else None,
            remaining_characters=cap.remaining_characters if cap else None,
            character_limit=cap.character_limit if cap else None,
            error=None if result.status == "connected" else result.message,
        )
        if result.status == "invalid_key":
            profile.status = ApiProfileStatus.INVALID
        elif result.status == "network_error":
            profile.status = ApiProfileStatus.UNAVAILABLE
        self.service.update_profile(profile)

    def _changed(self) -> None:
        self.voice_service.invalidate_provider_cache()
        self.refresh()
        self.profiles_changed.emit()

    def _selection_changed(self) -> None:
        has_selection = self.selected_profile() is not None
        for button in self.action_buttons[1:]:
            button.setEnabled(has_selection)
        row = self.table.currentRow()
        self.move_up_button.setEnabled(has_selection and row > 0)
        self.move_down_button.setEnabled(has_selection and 0 <= row < self.table.rowCount() - 1)
        self.more_button.setEnabled(True)
        self._update_details(self.selected_profile())

    def _update_details(self, profile: ApiProfile | None) -> None:
        enabled = profile is not None
        self.details_test.setEnabled(enabled)
        self.details_activate.setEnabled(enabled and not bool(profile.active) if profile else False)
        if profile is None:
            self.details_name.setText("No profile selected")
            self.details_status.setText("Select an account to see its connection status.")
            self.details_tier.setText("—")
            self.details_quota.setText("—")
            self.details_last_checked.setText("—")
            self.details_key.setText("—")
            return
        self.details_name.setText(profile.display_name)
        status = self._status_label(profile)
        if profile.last_error:
            status = f"{status}\n{profile.last_error}"
        self.details_status.setText(status)
        self.details_status.setToolTip(status)
        self.details_tier.setText(profile.account_tier or "Unknown")
        if profile.remaining_characters is None:
            self.details_quota.setText("Unavailable")
        elif profile.character_limit is not None:
            self.details_quota.setText(f"{profile.remaining_characters:,} remaining of {profile.character_limit:,}")
        else:
            self.details_quota.setText(f"{profile.remaining_characters:,} remaining")
        self.details_last_checked.setText(profile.last_checked_at or "Not checked")
        self.details_key.setText(profile.masked_key if profile.has_saved_key else "No saved credential")

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
