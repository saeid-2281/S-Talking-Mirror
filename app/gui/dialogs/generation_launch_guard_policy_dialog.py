from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_launch_receipt import GenerationLaunchGuardPolicy
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationLaunchGuardPolicyDialog(QDialog):
    """Configure project baseline drift protection without exposing credentials."""

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
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.saved_policy: GenerationLaunchGuardPolicy | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardPolicyDialog")
        self.setWindowTitle("Project launch baseline guard")
        self.resize(760, 610)
        self.setMinimumSize(620, 480)
        self._build()
        self.load_policy()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Project launch baseline guard",
            "Protect generation launches from accidental provider, output, scope or risk changes compared with a trusted receipt.",
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

        mode_section = DialogSection(
            "Guard mode",
            "Warn requires explicit acknowledgement. Enforce blocks critical protected drift until settings or policy are changed.",
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

        note = QLabel(
            "The guard policy stores only project name, mode and category names. API keys, credentials and receipt contents are never copied into the policy file."
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

        self.mode_combo.currentIndexChanged.connect(self._update_state)
        self.defaults_button.clicked.connect(self.restore_defaults)
        cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.save_policy)

    def load_policy(self) -> GenerationLaunchGuardPolicy:
        policy = self.service.guard_policy(self.project_name)
        index = self.mode_combo.findData(policy.mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        selected = set(policy.protected_categories)
        for category, box in self.category_boxes.items():
            box.setChecked(category in selected)
        self._update_state()
        return policy

    def selected_categories(self) -> tuple[str, ...]:
        return tuple(
            category
            for category, box in self.category_boxes.items()
            if box.isChecked()
        )

    def restore_defaults(self) -> None:
        warn_index = self.mode_combo.findData("warn")
        self.mode_combo.setCurrentIndex(max(0, warn_index))
        for box in self.category_boxes.values():
            box.setChecked(True)
        self.status_label.setText("Recommended baseline guard defaults restored.")
        self._update_state()

    def save_policy(self) -> GenerationLaunchGuardPolicy | None:
        mode = str(self.mode_combo.currentData() or "off")
        categories = self.selected_categories()
        try:
            self.service.set_guard_policy(
                self.project_name,
                mode=mode,
                protected_categories=categories,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.saved_policy = self.service.guard_policy(self.project_name)
        self.accept()
        return self.saved_policy

    def _update_state(self) -> None:
        mode = str(self.mode_combo.currentData() or "off")
        enabled = mode != "off"
        for box in self.category_boxes.values():
            box.setEnabled(enabled)
        selected = len(self.selected_categories())
        if mode == "off":
            self.status_card.update_status(
                "Baseline guard disabled",
                "Launches will not be compared with the project baseline before start.",
                tone="neutral",
            )
            self.save_button.setEnabled(True)
        elif mode == "enforce":
            self.status_card.update_status(
                "Critical baseline drift will be blocked",
                f"{selected:,} protected category group(s) are selected.",
                tone="warning",
            )
            self.save_button.setEnabled(selected > 0)
        else:
            self.status_card.update_status(
                "Protected drift requires acknowledgement",
                f"{selected:,} protected category group(s) are selected.",
                tone="info",
            )
            self.save_button.setEnabled(selected > 0)
