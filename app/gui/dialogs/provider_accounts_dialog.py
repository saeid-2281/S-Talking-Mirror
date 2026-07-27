from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSpinBox,
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
        self.resize(1040, 640)
        self.setMinimumSize(900, 560)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.addItem("ElevenLabs", "elevenlabs")
        top.addWidget(QLabel("Provider"))
        top.addWidget(self.provider)
        top.addStretch()
        root.addLayout(top)

        self.stack = QStackedWidget()
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
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
            empty_actions.addWidget(button)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_help)
        empty_layout.addLayout(empty_actions)
        empty_layout.addStretch()

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Active",
            "Profile name",
            "Provider",
            "Masked key",
            "Enabled",
            "Priority",
            "Connection",
            "Tier",
            "Remaining quota",
            "Last checked",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty_state)
        root.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        actions = [
            ("Add", "provider.add_profile", self.add_profile),
            ("Test", "provider.test_connection", self.test_selected),
            ("Set active", "provider.set_active_profile", self.set_active),
        ]
        self.action_buttons: list[QPushButton] = []
        for text, icon_name, handler in actions:
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.clicked.connect(handler)
            buttons.addWidget(button)
            self.action_buttons.append(button)
        self.move_up_button = QPushButton("")
        self.move_up_button.setIcon(action_icon("provider.move_up"))
        self.move_up_button.setToolTip("Move selected profile up")
        self.move_up_button.setAccessibleName("Move selected profile up")
        self.move_up_button.clicked.connect(lambda: self.move_profile(-1))
        self.move_down_button = QPushButton("")
        self.move_down_button.setIcon(action_icon("provider.move_down"))
        self.move_down_button.setToolTip("Move selected profile down")
        self.move_down_button.setAccessibleName("Move selected profile down")
        self.move_down_button.clicked.connect(lambda: self.move_profile(1))
        self.more_button = QPushButton("More")
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
        buttons.addStretch()
        root.addLayout(buttons)

        failover_box = QGroupBox("Failover")
        form = QFormLayout(failover_box)
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
        self.preview_label = QLabel("Preview unavailable")
        self.preview_label.setWordWrap(True)
        self.preview_button = QPushButton("Preview failover")
        self.preview_button.clicked.connect(self.preview_failover)
        self.save_failover_button = QPushButton("Save failover settings")
        self.save_failover_button.clicked.connect(self.save_failover)
        failover_box.setMaximumHeight(150)
        form.addRow("Mode", self.failover_mode)
        form.addRow("Maximum switches per run", self.max_switches)
        form.addRow("Sequence", self.sequence_mode)
        form.addRow("", self.allow_unknown_quota)
        form.addRow("", self.preview_button)
        form.addRow("Preview", self.preview_label)
        form.addRow("", self.save_failover_button)
        root.addWidget(failover_box)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close_row.addWidget(close)
        root.addLayout(close_row)
        self.provider.currentIndexChanged.connect(self.refresh)

    def refresh(self) -> None:
        provider = self.provider.currentData()
        selected_id = self.selected_profile().profile_id if self.selected_profile() else None
        profiles = self.service.list_profiles(provider)
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
