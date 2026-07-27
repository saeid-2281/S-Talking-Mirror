"""Reusable provider-panel controls for the v0.19 UI system."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.design_system import COMPACT


class ProviderField(QFrame):
    """A label, editor, and optional action with stable responsive geometry."""

    def __init__(self, label: str, editor: QWidget, action: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("providerField")
        self.label = QLabel(label)
        self.label.setObjectName("providerFieldLabel")
        self.label.setMinimumWidth(0)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        editor.setMinimumWidth(max(180, editor.minimumWidth()))
        editor.setMinimumHeight(max(COMPACT.control_height, editor.minimumHeight()))
        editor.setSizePolicy(QSizePolicy.Expanding, editor.sizePolicy().verticalPolicy())
        self.editor = editor
        self.action = action

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label)

        row = QFrame()
        row.setObjectName("providerFieldEditorRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(editor, 1)
        if action is not None:
            action.setFixedSize(COMPACT.icon_button, COMPACT.icon_button)
            row_layout.addWidget(action, 0, Qt.AlignTop)
        layout.addWidget(row)


class ProviderSection(QFrame):
    """Collapsible card-like section used by the Provider workspace."""

    expanded_changed = Signal(bool)

    def __init__(self, title: str, summary: str = "", expanded: bool = True) -> None:
        super().__init__()
        self.setObjectName("providerSection")
        self._title = title
        self.summary = summary

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QToolButton()
        self.header.setObjectName("providerSectionHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.clicked.connect(self.set_expanded)
        root.addWidget(self.header)

        self.content = QWidget()
        self.content.setObjectName("providerSectionContent")
        self.form = QVBoxLayout(self.content)
        self.form.setContentsMargins(10, 6, 10, 10)
        self.form.setSpacing(COMPACT.section_gap)
        root.addWidget(self.content)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        text = self._title
        if not expanded and self.summary:
            text = f"{text} · {self.summary}"
        self.header.setText(text)
        self.content.setVisible(expanded)
        self.expanded_changed.emit(expanded)

    def addRow(self, label: str, widget: QWidget) -> ProviderField:
        # Compatibility with the legacy MainWindow construction API.
        if isinstance(widget, QFrame) and widget.objectName() == "inlineFieldRow":
            field = QFrame()
            field.setObjectName("providerField")
            layout = QVBoxLayout(field)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            caption = QLabel(label)
            caption.setObjectName("providerFieldLabel")
            layout.addWidget(caption)
            widget.setMinimumHeight(COMPACT.control_height)
            layout.addWidget(widget)
        else:
            field = ProviderField(label, widget)
        self.form.addWidget(field)
        return field
