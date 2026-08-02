from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.interface_preferences import (
    ContrastMode,
    FocusStyle,
    InterfacePreferences,
    TEXT_SCALES,
)
from app.gui.widgets.dialog_workspace import DialogSection, DialogWorkspace
from app.gui.widgets.professional_components import PreferencePreview


class InterfacePreferencesDialog(QDialog):
    """Professional interface and accessibility preferences.

    Content scrolls independently while the Save/Cancel actions remain pinned
    to the bottom edge. This keeps the dialog usable with 125% text scaling and
    on shorter laptop displays.
    """

    def __init__(
        self,
        preferences: InterfacePreferences,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("interfacePreferencesDialog")
        self.setWindowTitle("Interface & Accessibility")
        self.setModal(True)
        self.resize(680, 620)
        self.setMinimumSize(520, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.workspace = DialogWorkspace(
            "Interface & accessibility",
            "Tune contrast, text scale, keyboard focus and status announcements "
            "without changing project or generation settings.",
            icon_name="settings",
            parent=self,
        )
        self.header = self.workspace.header
        root.addWidget(self.workspace)

        settings_section = DialogSection(
            "Visual and interaction settings",
            "Changes apply to the application interface only. Generated audio and project data are not modified.",
        )
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.contrast_combo = QComboBox()
        self.contrast_combo.setObjectName("interfaceContrast")
        self.contrast_combo.addItem("Standard contrast", ContrastMode.STANDARD.value)
        self.contrast_combo.addItem("High contrast", ContrastMode.HIGH.value)
        self.contrast_combo.setAccessibleName("Interface contrast")
        contrast_label = QLabel("Contrast")
        contrast_label.setBuddy(self.contrast_combo)
        contrast_label.setToolTip("High contrast strengthens borders and focus indicators.")
        form.addRow(contrast_label, self.contrast_combo)

        self.text_scale_combo = QComboBox()
        self.text_scale_combo.setObjectName("interfaceTextScale")
        for scale in TEXT_SCALES:
            self.text_scale_combo.addItem(f"{scale}%", scale)
        self.text_scale_combo.setAccessibleName("Interface text scale")
        scale_label = QLabel("Text scale")
        scale_label.setBuddy(self.text_scale_combo)
        scale_label.setToolTip("Changes interface text only; generated audio is unaffected.")
        form.addRow(scale_label, self.text_scale_combo)

        self.focus_combo = QComboBox()
        self.focus_combo.setObjectName("interfaceFocusStyle")
        self.focus_combo.addItem("Standard focus ring", FocusStyle.STANDARD.value)
        self.focus_combo.addItem("Enhanced focus ring", FocusStyle.ENHANCED.value)
        self.focus_combo.setAccessibleName("Keyboard focus visibility")
        focus_label = QLabel("Keyboard focus")
        focus_label.setBuddy(self.focus_combo)
        form.addRow(focus_label, self.focus_combo)

        self.reduce_motion_checkbox = QCheckBox(
            "Reduce non-essential interface motion"
        )
        self.reduce_motion_checkbox.setObjectName("interfaceReduceMotion")
        self.reduce_motion_checkbox.setAccessibleName("Reduce interface motion")
        form.addRow("Motion", self.reduce_motion_checkbox)

        self.announce_status_checkbox = QCheckBox(
            "Announce important status changes"
        )
        self.announce_status_checkbox.setObjectName("interfaceAnnounceStatus")
        self.announce_status_checkbox.setAccessibleName("Announce status changes")
        form.addRow("Status", self.announce_status_checkbox)

        settings_section.add_layout(form)
        self.workspace.add_body_widget(settings_section)

        self.preview = PreferencePreview()
        self.workspace.add_body_widget(self.preview)

        shortcut_section = DialogSection(
            "Keyboard navigation",
            "Move directly between major workspace regions without reaching for the mouse.",
        )
        shortcuts = QLabel(
            "Ctrl+1 Provider · Ctrl+2 Queue · Ctrl+3 Inspector · "
            "Ctrl+4 Activity · Ctrl+5 Generation controls · F6 Next region"
        )
        shortcuts.setObjectName("interfaceShortcutSummary")
        shortcuts.setWordWrap(True)
        shortcuts.setAccessibleName("Workspace keyboard shortcuts")
        shortcut_section.add_widget(shortcuts)
        self.workspace.add_body_widget(shortcut_section)
        self.workspace.add_body_stretch()

        self.restore_defaults_button = QPushButton("Restore defaults")
        self.restore_defaults_button.setObjectName("interfaceRestoreDefaults")
        self.restore_defaults_button.clicked.connect(self.restore_defaults)
        self.workspace.add_footer_widget(self.restore_defaults_button)
        self.workspace.add_footer_stretch()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.button_box.button(QDialogButtonBox.Save).setText("Save interface settings")
        self.button_box.button(QDialogButtonBox.Save).setObjectName("dialogPrimaryAction")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.workspace.add_footer_widget(self.button_box)

        self._load(preferences.normalized())
        for widget in (
            self.contrast_combo,
            self.text_scale_combo,
            self.focus_combo,
            self.reduce_motion_checkbox,
        ):
            signal = getattr(widget, "currentIndexChanged", None)
            if signal is None:
                signal = getattr(widget, "toggled")
            signal.connect(self.update_preview)

    def _load(self, preferences: InterfacePreferences) -> None:
        self.contrast_combo.setCurrentIndex(
            max(0, self.contrast_combo.findData(preferences.contrast.value))
        )
        self.text_scale_combo.setCurrentIndex(
            max(0, self.text_scale_combo.findData(preferences.text_scale))
        )
        self.focus_combo.setCurrentIndex(
            max(0, self.focus_combo.findData(preferences.focus_style.value))
        )
        self.reduce_motion_checkbox.setChecked(preferences.reduce_motion)
        self.announce_status_checkbox.setChecked(preferences.announce_status)
        self.update_preview()

    def restore_defaults(self) -> None:
        self._load(InterfacePreferences.defaults())

    def preferences(self) -> InterfacePreferences:
        return InterfacePreferences(
            contrast=ContrastMode(str(self.contrast_combo.currentData())),
            text_scale=int(self.text_scale_combo.currentData()),
            focus_style=FocusStyle(str(self.focus_combo.currentData())),
            reduce_motion=self.reduce_motion_checkbox.isChecked(),
            announce_status=self.announce_status_checkbox.isChecked(),
        ).normalized()

    def update_preview(self, *_args) -> None:  # noqa: ANN002
        value = self.preferences()
        self.preview.update_preview(
            contrast=value.contrast.value,
            text_scale=value.text_scale,
            focus_style=value.focus_style.value,
            reduce_motion=value.reduce_motion,
        )
