from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_launch_receipt import GenerationLaunchGuardPolicyProfile
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationLaunchGuardProfileEditorDialog(QDialog):
    """Create or update one reusable custom guard-policy profile."""

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
        parent: QWidget | None = None,
        *,
        profile: GenerationLaunchGuardPolicyProfile | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.profile = profile
        self.saved_profile: GenerationLaunchGuardPolicyProfile | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardProfileEditorDialog")
        self.setWindowTitle("Guard policy profile")
        self.resize(680, 610)
        self.setMinimumSize(560, 470)
        self._build()
        self._load()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Guard policy profile",
            "Create a reusable, secret-free template for project launch protection.",
            icon_name="settings",
            parent=self,
        )
        root.addWidget(self.workspace)

        section = DialogSection(
            "Profile definition",
            "Profiles store only mode and protected category names. Credentials and receipt content are never included.",
        )
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("guardProfileName")
        self.name_edit.setPlaceholderText("Example: Controlled production")
        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("guardProfileDescription")
        self.description_edit.setPlaceholderText("Explain when operators should use this profile…")
        self.description_edit.setMaximumHeight(90)
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("guardProfileMode")
        self.mode_combo.addItem("Off", "off")
        self.mode_combo.addItem("Warn", "warn")
        self.mode_combo.addItem("Enforce", "enforce")
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Guard mode", self.mode_combo)
        section.add_layout(form)
        self.workspace.add_body_widget(section)

        categories = DialogSection(
            "Protected categories",
            "Select the launch settings that participate in baseline drift decisions.",
        )
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in self.service.GUARD_CATEGORIES:
            box = QCheckBox(category)
            box.setObjectName("guardProfileCategory")
            box.setProperty("guardCategory", category)
            categories.add_widget(box)
            self.category_boxes[category] = box
        self.workspace.add_body_widget(categories, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        cancel = QPushButton("Cancel")
        save = QPushButton("Save profile")
        save.setObjectName("dialogPrimaryAction")
        save.setIcon(action_icon("save"))
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(cancel)
        self.workspace.add_footer_widget(save)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save_profile)
        self.mode_combo.currentIndexChanged.connect(self._update_categories)

    def _load(self) -> None:
        profile = self.profile
        if profile is None:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("warn"))
            for box in self.category_boxes.values():
                box.setChecked(True)
        else:
            self.name_edit.setText(profile.name)
            self.description_edit.setPlainText(profile.description)
            self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(profile.mode)))
            selected = set(profile.protected_categories)
            for category, box in self.category_boxes.items():
                box.setChecked(category in selected)
        self._update_categories()

    def selected_categories(self) -> tuple[str, ...]:
        return tuple(category for category, box in self.category_boxes.items() if box.isChecked())

    def _update_categories(self) -> None:
        enabled = str(self.mode_combo.currentData() or "off") != "off"
        for box in self.category_boxes.values():
            box.setEnabled(enabled)

    def save_profile(self) -> GenerationLaunchGuardPolicyProfile | None:
        try:
            self.saved_profile = self.service.save_guard_policy_profile(
                profile_id=self.profile.profile_id if self.profile is not None else "",
                name=self.name_edit.text(),
                description=self.description_edit.toPlainText(),
                mode=str(self.mode_combo.currentData() or "warn"),
                protected_categories=self.selected_categories(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.accept()
        return self.saved_profile


class GenerationLaunchGuardProfileDialog(QDialog):
    """Manage reusable templates and apply them to a project policy."""

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
        parent: QWidget | None = None,
        *,
        project_name: str = "",
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.export_dir = Path(export_dir or service.reports_dir / "guard-policy-profiles")
        self.profiles: list[GenerationLaunchGuardPolicyProfile] = []
        self.editor_dialogs: list[GenerationLaunchGuardProfileEditorDialog] = []
        self.applied_profile: GenerationLaunchGuardPolicyProfile | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardProfileDialog")
        self.setWindowTitle("Guard policy profiles")
        self.resize(980, 720)
        self.setMinimumSize(720, 520)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Guard policy profiles",
            "Reuse consistent launch protection across projects and keep project-specific overrides auditable.",
            icon_name="settings",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.summary = DialogStatusCard(
            "Policy templates",
            "Built-in profiles are read-only. Custom profiles can be imported, exported and reused.",
            tone="info",
        )
        self.summary.setObjectName("generationLaunchGuardProfileSummary")
        self.workspace.add_body_widget(self.summary)

        archive = DialogSection(
            "Available profiles",
            "The default profile initializes projects that do not yet have an explicit policy record.",
        )
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("generationLaunchGuardProfileTable")
        self.table.setHorizontalHeaderLabels(
            ["Default", "Type", "Name", "Mode", "Categories", "Profile ID"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        archive.add_widget(self.table, 1)
        self.workspace.add_body_widget(archive, 1)

        details_section = DialogSection(
            "Selected profile",
            "Compare the template with the active project policy before applying it.",
        )
        self.details = QPlainTextEdit()
        self.details.setObjectName("generationLaunchGuardProfileDetails")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(155)
        details_section.add_widget(self.details)
        self.lock_project = QCheckBox("Lock the project policy after applying this profile")
        self.lock_project.setObjectName("guardProfileLockProject")
        details_section.add_widget(self.lock_project)
        self.workspace.add_body_widget(details_section)

        actions = QHBoxLayout()
        self.create_button = QPushButton("New custom profile")
        self.edit_button = QPushButton("Edit custom")
        self.delete_button = QPushButton("Delete custom")
        self.default_button = QPushButton("Set as default")
        self.apply_button = QPushButton("Apply to project")
        self.apply_button.setObjectName("dialogPrimaryAction")
        for button, icon_name in (
            (self.create_button, "save"),
            (self.edit_button, "settings"),
            (self.delete_button, "general.clear"),
            (self.default_button, "general.refresh"),
            (self.apply_button, "save"),
        ):
            button.setIcon(action_icon(icon_name))
            actions.addWidget(button)
        actions.addStretch(1)
        action_section = DialogSection(
            "Profile actions",
            "Applying a profile creates a new project policy version instead of rewriting history.",
        )
        action_section.add_layout(actions)
        self.workspace.add_body_widget(action_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        import_button = QPushButton("Import")
        export_button = QPushButton("Export")
        close_button = QPushButton("Close")
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(import_button)
        self.workspace.add_footer_widget(export_button)
        self.workspace.add_footer_widget(close_button)

        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.create_button.clicked.connect(self.create_profile)
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.default_button.clicked.connect(self.set_selected_default)
        self.apply_button.clicked.connect(self.apply_selected)
        import_button.clicked.connect(self.import_profiles)
        export_button.clicked.connect(self.export_profiles)
        close_button.clicked.connect(self.accept)

    def refresh(self) -> None:
        selected_id = self.selected_profile().profile_id if self.selected_profile() else ""
        self.profiles = self.service.list_guard_policy_profiles()
        default_id = self.service.default_guard_policy_profile_id()
        self.table.setRowCount(len(self.profiles))
        for row, profile in enumerate(self.profiles):
            values = (
                "Yes" if profile.profile_id == default_id else "",
                "Built-in" if profile.built_in else "Custom",
                profile.name,
                profile.mode.title(),
                str(len(profile.protected_categories)),
                profile.profile_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, profile.profile_id)
                self.table.setItem(row, column, item)
        target_row = next(
            (index for index, item in enumerate(self.profiles) if item.profile_id == selected_id),
            0 if self.profiles else -1,
        )
        if target_row >= 0:
            self.table.selectRow(target_row)
        self.summary.update_status(
            f"{len(self.profiles):,} policy profile(s)",
            f"Default: {default_id}. Project: {self.project_name or 'not selected'}.",
            tone="success",
        )
        self._selection_changed()

    def selected_profile(self) -> GenerationLaunchGuardPolicyProfile | None:
        row = self.table.currentRow()
        return self.profiles[row] if 0 <= row < len(self.profiles) else None

    def _selection_changed(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            self.details.clear()
            for button in (self.edit_button, self.delete_button, self.default_button, self.apply_button):
                button.setEnabled(False)
            return
        policy = self.service.guard_policy(self.project_name) if self.project_name else None
        differences = self.service.compare_guard_policy_to_profile(policy, profile) if policy else ()
        lines = [
            f"{profile.name} ({profile.profile_id})",
            profile.description or "No description.",
            f"Mode: {profile.mode}",
            "Categories: " + (", ".join(profile.protected_categories) or "None"),
            "Project comparison: " + ("; ".join(differences) if differences else "matches current policy"),
        ]
        self.details.setPlainText("\n".join(lines))
        self.edit_button.setEnabled(not profile.built_in)
        self.delete_button.setEnabled(not profile.built_in)
        self.default_button.setEnabled(profile.profile_id != self.service.default_guard_policy_profile_id())
        self.apply_button.setEnabled(bool(self.project_name and self.project_name != "all-projects"))

    def create_profile(self) -> GenerationLaunchGuardProfileEditorDialog:
        dialog = GenerationLaunchGuardProfileEditorDialog(self.service, self)
        self.editor_dialogs.append(dialog)
        dialog.finished.connect(self._editor_finished)
        dialog.show()
        return dialog

    def edit_selected(self) -> GenerationLaunchGuardProfileEditorDialog | None:
        profile = self.selected_profile()
        if profile is None or profile.built_in:
            return None
        dialog = GenerationLaunchGuardProfileEditorDialog(self.service, self, profile=profile)
        self.editor_dialogs.append(dialog)
        dialog.finished.connect(self._editor_finished)
        dialog.show()
        return dialog

    def _editor_finished(self, _result: int) -> None:
        dialog = self.sender()
        if dialog in self.editor_dialogs:
            self.editor_dialogs.remove(dialog)
        self.refresh()

    def delete_selected(self) -> bool:
        profile = self.selected_profile()
        if profile is None:
            return False
        try:
            removed = self.service.delete_guard_policy_profile(profile.profile_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText("Custom profile deleted." if removed else "Profile not found.")
        self.refresh()
        return removed

    def set_selected_default(self) -> Path | None:
        profile = self.selected_profile()
        if profile is None:
            return None
        try:
            path = self.service.set_default_guard_policy_profile(profile.profile_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.status_label.setText(f"Default profile set to {profile.name}.")
        self.refresh()
        return path

    def apply_selected(self) -> GenerationLaunchGuardPolicyProfile | None:
        profile = self.selected_profile()
        if profile is None or not self.project_name or self.project_name == "all-projects":
            return None
        try:
            self.service.apply_guard_policy_profile(
                self.project_name,
                profile.profile_id,
                locked=self.lock_project.isChecked(),
                updated_by="Profile manager",
                override_lock=False,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.applied_profile = profile
        self.status_label.setText(f"Applied {profile.name} to {self.project_name}.")
        self._selection_changed()
        return profile

    def export_profiles(self, destination: Path | None = None) -> Path | None:
        if destination is None:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Export guard policy profiles",
                str(self.export_dir / "generation-launch-guard-policy-profiles.json"),
                "JSON files (*.json)",
            )
            if not selected:
                return None
            destination = Path(selected)
        path = self.service.export_guard_policy_profiles(Path(destination))
        self.status_label.setText(f"Exported: {path.name}")
        return path

    def import_profiles(self, source: Path | None = None) -> tuple[GenerationLaunchGuardPolicyProfile, ...]:
        if source is None:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Import guard policy profiles",
                str(self.export_dir),
                "JSON files (*.json)",
            )
            if not selected:
                return ()
            source = Path(selected)
        try:
            imported = self.service.import_guard_policy_profiles(Path(source))
        except (OSError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return ()
        self.status_label.setText(f"Imported {len(imported):,} custom profile(s).")
        self.refresh()
        return imported
