"""Roadmap 2 A10 dialog, form, and data-dense presentation modernization.

The layer is intentionally presentation-only. Existing dialogs retain their
controllers, signals, validation, persistence, provider selection, Preflight,
and generation authority. A10 standardizes layout rhythm and semantic styling
when an existing Qt dialog is shown.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QBoxLayout,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableView,
    QTextEdit,
    QTreeView,
    QWidget,
)

from app.gui.design_system import density_metrics, normalize_density
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


DIALOG_SURFACE_INVENTORY = (
    "ProviderAccountsDialog",
    "ProviderSetupWizardDialog",
    "UnifiedVoiceModelCatalogDialog",
    "ProviderCostQuotaLimitsDialog",
    "PreflightDialog",
    "PreflightFixDialog",
    "PronunciationDictionaryDialog",
    "PronunciationReviewDialog",
    "SourceImportReviewDialog",
    "CsvImportReviewDialog",
    "RecentProjectsDialog",
    "InterfacePreferencesDialog",
)

DATA_DENSE_SURFACES = (
    "tables",
    "trees",
    "lists",
    "catalogs",
    "review grids",
    "evidence views",
)


class DialogFormModernizer(QObject):
    """Apply Soft Professional dialog/form semantics to existing Qt surfaces."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.owner = owner
        self._installed = False
        self._density = normalize_density("compact")

    def install(self) -> None:
        application = QApplication.instance()
        if application is None or self._installed:
            return
        application.installEventFilter(self)
        self._installed = True
        self.refresh_open_dialogs()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Show and isinstance(watched, QDialog):
            self.polish_dialog(watched)
        return False

    @staticmethod
    def _is_native_system_dialog(dialog: QDialog) -> bool:
        return isinstance(dialog, (QFileDialog, QFontDialog))

    @property
    def control_height(self) -> int:
        return density_metrics(self._density).control_height

    def apply_density(self, name) -> None:  # noqa: ANN001
        self._density = normalize_density(name)
        self.refresh_open_dialogs()

    def refresh_open_dialogs(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        for widget in application.topLevelWidgets():
            if isinstance(widget, QDialog) and not self._is_native_system_dialog(widget):
                self.polish_dialog(widget)

    def polish_dialog(self, dialog: QDialog) -> None:
        if self._is_native_system_dialog(dialog):
            return
        dialog.setProperty("a10Modernized", True)
        dialog.setProperty("visualAlignment", "soft-professional")
        self._polish_layout_tree(dialog.layout(), root=True)
        self._polish_widget_tree(dialog)
        self._repolish(dialog)
        # Existing theme/density stylesheets can reassert their historical
        # min-height values during polish. Geometry is therefore enforced last.
        self._enforce_control_geometry(dialog)

    def _polish_layout_tree(self, layout, *, root: bool = False) -> None:  # noqa: ANN001
        if layout is None:
            return

        if root:
            margins = layout.contentsMargins()
            values = (margins.left(), margins.top(), margins.right(), margins.bottom())
            if min(values) >= 4 and max(values) <= 12:
                layout.setContentsMargins(16, 14, 16, 16)
            layout.setSpacing(max(10, layout.spacing()))

        if isinstance(layout, QFormLayout):
            layout.setHorizontalSpacing(max(12, layout.horizontalSpacing()))
            layout.setVerticalSpacing(max(8, layout.verticalSpacing()))
            layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
        elif isinstance(layout, QGridLayout):
            layout.setHorizontalSpacing(max(8, layout.horizontalSpacing()))
            layout.setVerticalSpacing(max(8, layout.verticalSpacing()))
        elif isinstance(layout, QBoxLayout):
            layout.setSpacing(max(8, layout.spacing()))

        for index in range(layout.count()):
            item = layout.itemAt(index)
            child_layout = item.layout() if item is not None else None
            if child_layout is not None:
                self._polish_layout_tree(child_layout)

    def _polish_widget_tree(self, root: QWidget) -> None:
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            if isinstance(widget, QGroupBox):
                widget.setProperty("visualRole", "formSection")
            elif isinstance(widget, QDialogButtonBox):
                self._polish_button_box(widget)
            elif isinstance(widget, QTabWidget):
                widget.setProperty("visualRole", "dialogTabs")
                widget.setDocumentMode(True)
            elif isinstance(widget, QScrollArea):
                widget.setProperty("visualRole", "dialogScroll")
            elif isinstance(widget, (QTableView, QTreeView, QListView)):
                widget.setProperty("visualRole", "dataDense")
                widget.setAlternatingRowColors(True)
            elif isinstance(widget, (QLineEdit, QComboBox, QAbstractSpinBox)):
                widget.setProperty("visualRole", "formControl")
                widget.setMinimumHeight(max(widget.minimumHeight(), self.control_height))
            elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
                widget.setProperty("visualRole", "multilineFormControl")
            elif isinstance(widget, QLabel) and widget.buddy() is not None:
                widget.setProperty("visualRole", "formLabel")


    def _enforce_control_geometry(self, root: QWidget) -> None:
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            if isinstance(widget, (QLineEdit, QComboBox, QAbstractSpinBox)):
                widget.setMinimumHeight(max(widget.minimumHeight(), self.control_height))
            elif isinstance(widget, QDialogButtonBox):
                for button in widget.buttons():
                    if not isinstance(button, QPushButton):
                        continue
                    button.setMinimumHeight(max(button.minimumHeight(), self.control_height))
                    if button.text().strip():
                        button.setMinimumWidth(max(button.minimumWidth(), 84))


    @staticmethod
    def _repolish(dialog: QDialog) -> None:
        widgets = [dialog, *dialog.findChildren(QWidget)]
        for widget in widgets:
            style = widget.style()
            if style is None:
                continue
            style.unpolish(widget)
            style.polish(widget)
        dialog.update()

    def _polish_button_box(self, button_box: QDialogButtonBox) -> None:
        button_box.setProperty("visualRole", "dialogActions")
        for button in button_box.buttons():
            if not isinstance(button, QPushButton):
                continue
            button.setProperty("visualRole", "dialogAction")
            button.setMinimumHeight(max(button.minimumHeight(), self.control_height))
            if button.text().strip():
                button.setMinimumWidth(max(button.minimumWidth(), 84))


def dialog_form_stylesheet(
    *,
    is_dark: bool = False,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Return the A10 Soft Professional dialog/form/data-grid overlay."""

    palette = palette_for(is_dark=is_dark, concept_key=concept_key)
    p = palette
    return f"""
/* Roadmap 2 A10 — Dialogs, Forms & Data-Dense UX */
QDialog[a10Modernized="true"] {{
    background:{p.canvas};
    color:{p.text_primary};
}}
QDialog[a10Modernized="true"] QGroupBox[visualRole="formSection"] {{
    background:{p.surface};
    color:{p.text_primary};
    border:1px solid {p.border};
    border-radius:12px;
    margin-top:12px;
    padding:12px 10px 10px 10px;
    font-weight:700;
}}
QDialog[a10Modernized="true"] QGroupBox[visualRole="formSection"]::title {{
    subcontrol-origin:margin;
    left:10px;
    padding:0 5px;
    color:{p.text_secondary};
    background:{p.canvas};
}}
QDialog[a10Modernized="true"] QLabel[visualRole="formLabel"] {{
    color:{p.text_secondary};
    font-weight:600;
    background:transparent;
}}
QDialog[a10Modernized="true"] QLineEdit[visualRole="formControl"],
QDialog[a10Modernized="true"] QComboBox[visualRole="formControl"],
QDialog[a10Modernized="true"] QAbstractSpinBox[visualRole="formControl"] {{
    background:{p.surface};
    color:{p.text_primary};
    border:1px solid {p.border_strong};
    border-radius:8px;
    padding:0 9px;
    selection-background-color:{p.primary_soft};
    selection-color:{p.text_primary};
}}
QDialog[a10Modernized="true"] QLineEdit[visualRole="formControl"]:focus,
QDialog[a10Modernized="true"] QComboBox[visualRole="formControl"]:focus,
QDialog[a10Modernized="true"] QAbstractSpinBox[visualRole="formControl"]:focus {{
    border:1px solid {p.primary};
}}
QDialog[a10Modernized="true"] QLineEdit[visualRole="formControl"]:disabled,
QDialog[a10Modernized="true"] QComboBox[visualRole="formControl"]:disabled,
QDialog[a10Modernized="true"] QAbstractSpinBox[visualRole="formControl"]:disabled {{
    background:{p.surface_secondary};
    color:{p.text_muted};
}}
QDialog[a10Modernized="true"] QPlainTextEdit[visualRole="multilineFormControl"],
QDialog[a10Modernized="true"] QTextEdit[visualRole="multilineFormControl"] {{
    background:{p.surface};
    color:{p.text_primary};
    border:1px solid {p.border};
    border-radius:10px;
    padding:8px;
    selection-background-color:{p.primary_soft};
}}
QDialog[a10Modernized="true"] QDialogButtonBox[visualRole="dialogActions"] {{
    background:{p.surface_secondary};
    border-top:1px solid {p.border};
    padding:10px 12px;
}}
QDialog[a10Modernized="true"] QDialogButtonBox[visualRole="dialogActions"] QPushButton[visualRole="dialogAction"] {{
    background:{p.surface};
    color:{p.text_primary};
    border:1px solid {p.border_strong};
    border-radius:8px;
    padding:0 14px;
}}
QDialog[a10Modernized="true"] QDialogButtonBox[visualRole="dialogActions"] QPushButton[visualRole="dialogAction"]:hover {{
    background:{p.surface_secondary};
    border-color:{p.primary};
}}
QDialog[a10Modernized="true"] QDialogButtonBox[visualRole="dialogActions"] QPushButton[visualRole="dialogAction"]:default {{
    background:{p.primary};
    color:{p.text_inverse};
    border-color:{p.primary};
}}
QDialog[a10Modernized="true"] QTabWidget[visualRole="dialogTabs"]::pane {{
    background:{p.surface};
    border:1px solid {p.border};
    border-radius:10px;
    top:-1px;
}}
QDialog[a10Modernized="true"] QTabWidget[visualRole="dialogTabs"] QTabBar::tab {{
    background:transparent;
    color:{p.text_secondary};
    border:0;
    border-bottom:2px solid transparent;
    padding:8px 12px;
}}
QDialog[a10Modernized="true"] QTabWidget[visualRole="dialogTabs"] QTabBar::tab:selected {{
    color:{p.primary};
    border-bottom-color:{p.primary};
    font-weight:700;
}}
QDialog[a10Modernized="true"] QScrollArea[visualRole="dialogScroll"] {{
    background:transparent;
    border:0;
}}
QDialog[a10Modernized="true"] QTableView[visualRole="dataDense"],
QDialog[a10Modernized="true"] QTreeView[visualRole="dataDense"],
QDialog[a10Modernized="true"] QListView[visualRole="dataDense"] {{
    background:{p.surface};
    alternate-background-color:{p.surface_secondary};
    color:{p.text_primary};
    border:1px solid {p.border};
    border-radius:9px;
    gridline-color:{p.border};
    selection-background-color:{p.primary_soft};
    selection-color:{p.text_primary};
    outline:0;
}}
QDialog[a10Modernized="true"] QHeaderView::section {{
    background:{p.surface_secondary};
    color:{p.text_secondary};
    border:0;
    border-bottom:1px solid {p.border};
    padding:7px 8px;
    font-weight:700;
}}
"""
