from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon


class DialogHeader(QFrame):
    """Reusable dialog heading with a strong title and concise supporting copy."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        icon_name: str = "settings",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("professionalDialogHeader")
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("professionalDialogIcon")
        self.icon_label.setPixmap(action_icon(icon_name, size=24).pixmap(24, 24))
        self.icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.icon_label.setFixedWidth(30)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("professionalDialogTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("professionalDialogSubtitle")
        self.subtitle_label.setWordWrap(True)
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)

        layout.addWidget(self.icon_label)
        layout.addLayout(text, 1)


class PreferencePreview(QFrame):
    """Small live preview used by interface/accessibility preferences."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("interfacePreviewCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        self.title_label = QLabel("Interface preview")
        self.title_label.setObjectName("interfacePreviewTitle")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("interfacePreviewStatus")
        self.status_label.setAlignment(Qt.AlignCenter)
        heading.addWidget(self.title_label)
        heading.addStretch(1)
        heading.addWidget(self.status_label)

        self.body_label = QLabel(
            "Primary actions stay prominent, keyboard focus remains visible, "
            "and operational status is communicated with text as well as color."
        )
        self.body_label.setObjectName("interfacePreviewBody")
        self.body_label.setWordWrap(True)

        self.shortcut_label = QLabel("Keyboard: F6 cycles major regions · Ctrl+2 focuses the queue")
        self.shortcut_label.setObjectName("interfacePreviewShortcut")
        self.shortcut_label.setWordWrap(True)

        layout.addLayout(heading)
        layout.addWidget(self.body_label)
        layout.addWidget(self.shortcut_label)

    def update_preview(
        self,
        *,
        contrast: str,
        text_scale: int,
        focus_style: str,
        reduce_motion: bool,
    ) -> None:
        self.setProperty("contrastMode", contrast)
        self.setProperty("textScale", str(text_scale))
        self.setProperty("focusMode", focus_style)
        self.setProperty("reduceMotion", "true" if reduce_motion else "false")
        self.status_label.setText("High contrast" if contrast == "high" else "Ready")
        self.status_label.setProperty("tone", "info" if contrast == "high" else "success")
        self.style().unpolish(self)
        self.style().polish(self)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class LiveStatusAnnouncer(QLabel):
    """One-pixel accessible status target for screen readers and tests.

    It does not compete with the visible status bar. Updating its accessible
    name/description gives assistive technology a stable object whose content
    mirrors significant operational state transitions.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("accessibilityAnnouncer")
        self.setAccessibleName("Application status")
        self.setAccessibleDescription("Ready")
        self.setFixedSize(1, 1)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setText("")

    def announce(self, message: str, *, category: str = "status") -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.setText(text)
        self.setAccessibleName(f"{category.title()}: {text}")
        self.setAccessibleDescription(text)
        self.setToolTip(text)


class EmptyStateCard(QFrame):
    """Reusable, action-oriented empty state for workspaces and dialogs.

    Empty screens should explain what happened and provide the next practical
    action instead of leaving a large blank surface. The component intentionally
    exposes the generated action buttons so existing windows can preserve their
    public handles while migrating to the shared visual language.
    """

    def __init__(
        self,
        title: str,
        message: str,
        *,
        icon_name: str = "general.info",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("professionalEmptyState")
        self.setMaximumWidth(560)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setAccessibleName(title)
        self.setAccessibleDescription(message)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("professionalEmptyStateIcon")
        self.icon_label.setPixmap(action_icon(icon_name, size=34).pixmap(34, 34))
        self.icon_label.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("professionalEmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)

        self.message_label = QLabel(message)
        self.message_label.setObjectName("professionalEmptyStateMessage")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 4, 0, 0)
        self.actions_layout.setSpacing(8)
        self.actions_layout.addStretch(1)
        self._action_buttons: list[QPushButton] = []

        root.addWidget(self.icon_label)
        root.addWidget(self.title_label)
        root.addWidget(self.message_label)
        root.addLayout(self.actions_layout)

    def add_action(
        self,
        text: str,
        callback: Callable[[], None],
        *,
        icon_name: str | None = None,
        primary: bool = False,
        tooltip: str = "",
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("professionalEmptyStatePrimary" if primary else "professionalEmptyStateAction")
        if icon_name:
            button.setIcon(action_icon(icon_name))
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        # Insert before the trailing stretch so the action group remains centered.
        self.actions_layout.insertWidget(max(0, self.actions_layout.count() - 1), button)
        self._action_buttons.append(button)
        return button

    def set_content(self, title: str, message: str, *, icon_name: str | None = None) -> None:
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.setAccessibleName(title)
        self.setAccessibleDescription(message)
        if icon_name:
            self.icon_label.setPixmap(action_icon(icon_name, size=34).pixmap(34, 34))


class InlineFeedbackBar(QFrame):
    """Compact visible feedback for filters and completed user operations."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inlineFeedbackBar")
        self.setProperty("tone", "neutral")
        self.setAccessibleName("Workspace feedback")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("inlineFeedbackIcon")
        self.message_label = QLabel("Ready")
        self.message_label.setObjectName("inlineFeedbackMessage")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.message_label, 1)
        self.show_message("Ready", tone="neutral")

    def show_message(self, message: str, *, tone: str = "neutral") -> None:
        normalized = tone if tone in {"neutral", "info", "success", "warning", "error"} else "neutral"
        icon_name = {
            "neutral": "general.info",
            "info": "general.info",
            "success": "general.success",
            "warning": "general.warning",
            "error": "general.error",
        }[normalized]
        self.icon_label.setPixmap(action_icon(icon_name, size=16).pixmap(16, 16))
        self.message_label.setText(str(message))
        self.setAccessibleDescription(str(message))
        self.setProperty("tone", normalized)
        self.style().unpolish(self)
        self.style().polish(self)
