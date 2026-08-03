from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_launch_receipt import GenerationLaunchGuardPolicy
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationLaunchGuardPolicyDialog(QDialog):
    """Configure versioned project baseline drift protection from reusable profiles."""

    CATEGORY_LABELS = {
        "Provider": "Provider, model and voice",
        "Output format": "Language and output format",
        "Output policy": "Output folder and replacement policy",
        "Execution": "Scope, order, retries and request delay",
        "Scope": "Planned files, characters and provider requests",
        "Risk and cost": "Planning risk and estimated cost",
        "Integrity": "Receipt and baseline integrity",
    }

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
        project_name: str,
        parent: QWidget | None = None,
        *,
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.export_dir = Path(export_dir or service.reports_dir / "guard-policy-profiles")
        self.saved_policy: GenerationLaunchGuardPolicy | None = None
        self.loaded_policy: GenerationLaunchGuardPolicy | None = None
        self.profile_dialogs: list[QDialog] = []
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardPolicyDialog")
        self.setWindowTitle("Project launch baseline guard")
        self.resize(820, 760)
        self.setMinimumSize(650, 520)
        self._build()
        self.load_policy()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Project launch baseline guard",
            "Apply reusable policy profiles, protect project-specific overrides and preserve every revision in an audit history.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.status_card = DialogStatusCard(
            "Baseline guard policy",
            "Choose how protected launch changes are handled before generation starts.",
            tone="info",
        )
        self.status_card.setObjectName("generationLaunchGuardStatusCard")
        self.workspace.add_body_widget(self.status_card)

        profile_section = DialogSection(
            "Policy profile",
            "Profiles provide consistent defaults across projects. Manual edits become a project-specific custom policy revision.",
        )
        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 0, 0, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("generationLaunchGuardProfile")
        self.apply_profile_button = QPushButton("Apply selected profile")
        self.apply_profile_button.setIcon(action_icon("general.refresh"))
        self.manage_profiles_button = QPushButton("Manage profiles")
        self.manage_profiles_button.setIcon(action_icon("settings"))
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.apply_profile_button)
        profile_row.addWidget(self.manage_profiles_button)
        profile_section.add_layout(profile_row)
        self.profile_comparison = QLabel("Select a profile to compare it with this project policy.")
        self.profile_comparison.setObjectName("historySummaryText")
        self.profile_comparison.setWordWrap(True)
        profile_section.add_widget(self.profile_comparison)
        self.workspace.add_body_widget(profile_section)

        mode_section = DialogSection(
            "Guard mode",
            "Warn requires explicit acknowledgement. Enforce blocks critical protected drift until settings, policy or approval changes.",
        )
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("generationLaunchGuardMode")
        self.mode_combo.addItem("Off — do not compare before launch", "off")
        self.mode_combo.addItem("Warn — require acknowledgement", "warn")
        self.mode_combo.addItem("Enforce — block critical drift", "enforce")
        mode_section.add_widget(self.mode_combo)
        self.workspace.add_body_widget(mode_section)

        categories_section = DialogSection(
            "Protected launch categories",
            "Only selected categories participate in the pre-launch guard decision.",
        )
        self.category_frame = QFrame()
        self.category_frame.setObjectName("generationLaunchGuardCategories")
        category_layout = QVBoxLayout(self.category_frame)
        category_layout.setContentsMargins(10, 8, 10, 8)
        category_layout.setSpacing(7)
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in self.service.GUARD_CATEGORIES:
            box = QCheckBox(self.CATEGORY_LABELS.get(category, category))
            box.setObjectName("generationLaunchGuardCategory")
            box.setProperty("guardCategory", category)
            box.setToolTip(category)
            category_layout.addWidget(box)
            self.category_boxes[category] = box
        categories_section.add_widget(self.category_frame)
        self.workspace.add_body_widget(categories_section, 1)

        governance = DialogSection(
            "Policy governance",
            "A locked policy rejects accidental changes until an operator explicitly unlocks it. Every save creates a new version.",
        )
        self.lock_policy = QCheckBox("Lock this project policy after saving")
        self.lock_policy.setObjectName("generationLaunchGuardPolicyLock")
        self.updated_by = QLineEdit()
        self.updated_by.setObjectName("generationLaunchGuardPolicyUpdatedBy")
        self.updated_by.setPlaceholderText("Operator name")
        self.updated_by.setText("Operator")
        self.change_note = QLineEdit()
        self.change_note.setObjectName("generationLaunchGuardPolicyNote")
        self.change_note.setPlaceholderText("Optional reason for this policy revision")
        governance.add_widget(self.lock_policy)
        governance.add_widget(self.updated_by)
        governance.add_widget(self.change_note)
        self.workspace.add_body_widget(governance)

        history_section = DialogSection(
            "Policy history",
            "Recent revisions show the actor, applied profile, mode, lock state and reason.",
        )
        self.history_view = QPlainTextEdit()
        self.history_view.setObjectName("generationLaunchGuardPolicyHistory")
        self.history_view.setReadOnly(True)
        self.history_view.setMaximumHeight(135)
        history_section.add_widget(self.history_view)
        self.workspace.add_body_widget(history_section)

        note = QLabel(
            "Guard policies and profiles store only project name, mode, category names, version metadata and operator notes. API keys, credentials and receipt contents are never copied into these files."
        )
        note.setObjectName("historySummaryText")
        note.setWordWrap(True)
        self.workspace.add_body_widget(note)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setWordWrap(True)
        self.defaults_button = QPushButton("Restore recommended defaults")
        self.defaults_button.setIcon(action_icon("general.refresh"))
        cancel_button = QPushButton("Cancel")
        self.save_button = QPushButton("Save guard policy")
        self.save_button.setObjectName("dialogPrimaryAction")
        self.save_button.setIcon(action_icon("save"))
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(self.defaults_button)
        self.workspace.add_footer_widget(cancel_button)
        self.workspace.add_footer_widget(self.save_button)

        self.mode_combo.currentIndexChanged.connect(self._manual_change)
        self.profile_combo.currentIndexChanged.connect(self._profile_selection_changed)
        self.apply_profile_button.clicked.connect(self.apply_selected_profile)
        self.manage_profiles_button.clicked.connect(self.open_profile_manager)
        self.defaults_button.clicked.connect(self.restore_defaults)
        self.lock_policy.toggled.connect(self._update_state)
        cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.save_policy)

    def refresh_profiles(self) -> None:
        selected_id = str(self.profile_combo.currentData() or "")
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.service.list_guard_policy_profiles():
            label = f"{profile.name} · {profile.mode.title()}"
            if profile.profile_id == self.service.default_guard_policy_profile_id():
                label += " · Default"
            self.profile_combo.addItem(label, profile.profile_id)
        target = self.profile_combo.findData(selected_id)
        self.profile_combo.setCurrentIndex(max(0, target))
        self.profile_combo.blockSignals(False)
        self._profile_selection_changed()

    def load_policy(self) -> GenerationLaunchGuardPolicy:
        self.loaded_policy = self.service.guard_policy(self.project_name)
        policy = self.loaded_policy
        self.refresh_profiles()
        index = self.mode_combo.findData(policy.mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        selected = set(policy.protected_categories)
        for category, box in self.category_boxes.items():
            box.setChecked(category in selected)
        profile_index = self.profile_combo.findData(policy.profile_id)
        if profile_index >= 0:
            self.profile_combo.setCurrentIndex(profile_index)
        self.lock_policy.setChecked(policy.locked)
        self.updated_by.setText(policy.updated_by or "Operator")
        self._refresh_history()
        self._update_state()
        return policy

    def selected_categories(self) -> tuple[str, ...]:
        return tuple(
            category
            for category, box in self.category_boxes.items()
            if box.isChecked()
        )

    def restore_defaults(self) -> None:
        profile_id = self.service.default_guard_policy_profile_id()
        index = self.profile_combo.findData(profile_id)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        self.apply_selected_profile()
        self.lock_policy.setChecked(False)
        self.status_label.setText("Default guard policy profile restored locally. Save to create a new project version.")

    def apply_selected_profile(self) -> None:
        profile = self.service.guard_policy_profile(str(self.profile_combo.currentData() or ""))
        if profile is None:
            self.status_label.setText("Select an existing guard policy profile.")
            return
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(profile.mode)))
        self.mode_combo.blockSignals(False)
        selected = set(profile.protected_categories)
        for category, box in self.category_boxes.items():
            box.setChecked(category in selected)
        self.status_label.setText(f"{profile.name} loaded. Save to apply it to {self.project_name}.")
        self._update_state()

    def save_policy(self) -> GenerationLaunchGuardPolicy | None:
        mode = str(self.mode_combo.currentData() or "off")
        categories = self.selected_categories()
        selected_profile = self.service.guard_policy_profile(str(self.profile_combo.currentData() or ""))
        profile_id = ""
        if selected_profile is not None and not self.service.compare_guard_policy_to_profile(
            GenerationLaunchGuardPolicy(
                project_name=self.project_name,
                mode=mode,
                protected_categories=categories,
            ),
            selected_profile,
        ):
            profile_id = selected_profile.profile_id
        loaded = self.loaded_policy or self.service.guard_policy(self.project_name)
        unlocking = loaded.locked and not self.lock_policy.isChecked()
        try:
            self.service.set_guard_policy(
                self.project_name,
                mode=mode,
                protected_categories=categories,
                profile_id=profile_id,
                locked=self.lock_policy.isChecked(),
                updated_by=self.updated_by.text().strip() or "Operator",
                note=self.change_note.text().strip(),
                override_lock=unlocking,
                action="unlocked" if unlocking else "updated",
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.saved_policy = self.service.guard_policy(self.project_name)
        self.accept()
        return self.saved_policy

    def open_profile_manager(self) -> QDialog:
        from app.gui.dialogs.generation_launch_guard_profile_dialog import (
            GenerationLaunchGuardProfileDialog,
        )

        dialog = GenerationLaunchGuardProfileDialog(
            self.service,
            self,
            project_name=self.project_name,
            export_dir=self.export_dir,
        )
        self.profile_dialogs.append(dialog)
        dialog.finished.connect(self._profile_manager_finished)
        dialog.show()
        return dialog

    def _profile_manager_finished(self, _result: int) -> None:
        dialog = self.sender()
        if dialog in self.profile_dialogs:
            self.profile_dialogs.remove(dialog)
        self.load_policy()

    def _manual_change(self) -> None:
        self._update_state()
        self._profile_selection_changed()

    def _profile_selection_changed(self) -> None:
        profile = self.service.guard_policy_profile(str(self.profile_combo.currentData() or ""))
        if profile is None:
            self.profile_comparison.setText("Select a profile to compare it with this project policy.")
            return
        current = GenerationLaunchGuardPolicy(
            project_name=self.project_name,
            mode=str(self.mode_combo.currentData() or "off"),
            protected_categories=self.selected_categories(),
        )
        differences = self.service.compare_guard_policy_to_profile(current, profile)
        self.profile_comparison.setText(
            f"{profile.description} "
            + ("Current controls match this profile." if not differences else "Differences: " + "; ".join(differences))
        )

    def _refresh_history(self) -> None:
        history = self.service.guard_policy_history(self.project_name)
        if not history:
            self.history_view.setPlainText("No explicit project policy revisions yet. The default profile is currently inherited.")
            return
        lines = []
        for item in history[:12]:
            profile = item.profile_name or item.profile_id or "Custom"
            lock_state = "locked" if item.locked else "unlocked"
            note = f" · {item.note}" if item.note else ""
            lines.append(
                f"v{item.version} · {item.action} · {profile} · {item.mode} · {lock_state} · {item.actor or 'Operator'} · {item.occurred_at}{note}"
            )
        self.history_view.setPlainText("\n".join(lines))

    def _update_state(self) -> None:
        mode = str(self.mode_combo.currentData() or "off")
        selected = len(self.selected_categories())
        loaded_locked = bool(self.loaded_policy and self.loaded_policy.locked)
        controls_enabled = not loaded_locked or not self.lock_policy.isChecked()
        self.mode_combo.setEnabled(controls_enabled)
        self.profile_combo.setEnabled(controls_enabled)
        self.apply_profile_button.setEnabled(controls_enabled)
        for box in self.category_boxes.values():
            box.setEnabled(controls_enabled and mode != "off")
        version = self.loaded_policy.version if self.loaded_policy else 0
        profile_name = self.loaded_policy.profile_name if self.loaded_policy else "Default"
        if loaded_locked and self.lock_policy.isChecked():
            self.status_card.update_status(
                "Project policy is locked",
                f"Version {version} · {profile_name}. Clear the lock checkbox to authorize a new revision.",
                tone="warning",
            )
            self.save_button.setEnabled(False)
        elif mode == "off":
            self.status_card.update_status(
                "Baseline guard disabled",
                f"Saving creates version {version + 1}. Launches will not be compared with the project baseline.",
                tone="neutral",
            )
            self.save_button.setEnabled(True)
        elif mode == "enforce":
            self.status_card.update_status(
                "Critical baseline drift will be blocked",
                f"{selected:,} protected category group(s) · next version {version + 1}.",
                tone="warning",
            )
            self.save_button.setEnabled(selected > 0)
        else:
            self.status_card.update_status(
                "Protected drift requires acknowledgement",
                f"{selected:,} protected category group(s) · next version {version + 1}.",
                tone="info",
            )
            self.save_button.setEnabled(selected > 0)
        self._profile_selection_changed()
