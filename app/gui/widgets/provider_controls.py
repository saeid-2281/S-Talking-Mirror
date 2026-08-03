"""Reusable provider-panel controls for the v0.19 UI system."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.design_system import COMPACT
from app.gui.icons import action_icon


class ProviderCapabilityBadge(QLabel):
    """Small, readable capability chip used by the provider overview."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("providerCapabilityBadge")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.setVisible(bool(text))


class ProviderOverviewCard(QFrame):
    """A concise readiness summary above the detailed provider form.

    The card intentionally contains no provider business logic. MainWindow
    supplies already-resolved display values so this component remains easy to
    test and safe to reuse in future setup dialogs.
    """

    MAX_BADGES = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("providerOverviewCard")
        self.setAccessibleName("Provider readiness overview")

        root = QVBoxLayout(self)
        root.setContentsMargins(11, 10, 11, 10)
        root.setSpacing(7)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("providerOverviewIcon")
        self.icon_label.setPixmap(action_icon("general.account", size=18).pixmap(18, 18))
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignCenter)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(0)
        self.name_label = QLabel("Mock / Test Provider")
        self.name_label.setObjectName("providerOverviewName")
        self.mode_label = QLabel("Local provider")
        self.mode_label.setObjectName("providerOverviewMode")
        identity.addWidget(self.name_label)
        identity.addWidget(self.mode_label)

        self.status_badge = QLabel("Not tested")
        self.status_badge.setObjectName("providerReadinessBadge")
        self.status_badge.setProperty("tone", "neutral")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        heading.addWidget(self.icon_label)
        heading.addLayout(identity, 1)
        heading.addWidget(self.status_badge, 0, Qt.AlignTop)
        root.addLayout(heading)

        facts = QGridLayout()
        facts.setContentsMargins(0, 0, 0, 0)
        facts.setHorizontalSpacing(8)
        facts.setVerticalSpacing(3)
        profile_caption = QLabel("Profile")
        profile_caption.setObjectName("providerOverviewCaption")
        quota_caption = QLabel("Quota")
        quota_caption.setObjectName("providerOverviewCaption")
        self.profile_label = QLabel("Temporary key / no profile")
        self.profile_label.setObjectName("providerOverviewValue")
        self.profile_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.quota_label = QLabel("Not available")
        self.quota_label.setObjectName("providerOverviewValue")
        self.quota_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        facts.addWidget(profile_caption, 0, 0)
        facts.addWidget(self.profile_label, 0, 1)
        facts.addWidget(quota_caption, 1, 0)
        facts.addWidget(self.quota_label, 1, 1)
        facts.setColumnStretch(1, 1)
        root.addLayout(facts)

        self.badge_host = QFrame()
        self.badge_host.setObjectName("providerCapabilityHost")
        badge_layout = QGridLayout(self.badge_host)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setHorizontalSpacing(5)
        badge_layout.setVerticalSpacing(5)
        self.capability_badges: list[ProviderCapabilityBadge] = []
        for index in range(self.MAX_BADGES):
            badge = ProviderCapabilityBadge()
            self.capability_badges.append(badge)
            badge_layout.addWidget(badge, index // 3, index % 3)
        for column in range(3):
            badge_layout.setColumnStretch(column, 1)
        root.addWidget(self.badge_host)

        self.next_step_label = QLabel("Test the provider connection before generation.")
        self.next_step_label.setObjectName("providerNextStep")
        self.next_step_label.setWordWrap(True)
        root.addWidget(self.next_step_label)

    def update_summary(
        self,
        *,
        display_name: str,
        provider_mode: str,
        status: str,
        tone: str,
        profile: str,
        quota: str,
        capabilities: tuple[str, ...],
        next_step: str,
    ) -> None:
        self.name_label.setText(display_name or "Provider")
        self.mode_label.setText(provider_mode)
        self.status_badge.setText(status or "Not tested")
        self.status_badge.setProperty("tone", tone or "neutral")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.profile_label.setText(profile or "Temporary key / no profile")
        self.profile_label.setToolTip(profile or "Temporary key / no profile")
        self.quota_label.setText(quota or "Not available")
        self.quota_label.setToolTip(quota or "Not available")
        for index, badge in enumerate(self.capability_badges):
            text = capabilities[index] if index < len(capabilities) else ""
            badge.setText(text)
            badge.setVisible(bool(text))
        self.next_step_label.setText(next_step)
        self.setAccessibleDescription(
            f"{display_name}. {status}. Profile: {profile}. Quota: {quota}. {next_step}"
        )


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

    def __init__(
        self,
        title: str,
        summary: str = "",
        expanded: bool = True,
        description: str = "",
    ) -> None:
        super().__init__()
        self.setObjectName("providerSection")
        self._title = title
        self.summary = summary
        self.description = description

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QToolButton()
        self.header.setObjectName("providerSectionHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setArrowType(Qt.NoArrow)
        self.header.setIconSize(QSize(14, 14))
        self.header.clicked.connect(self.set_expanded)
        root.addWidget(self.header)

        self.content = QWidget()
        self.content.setObjectName("providerSectionContent")
        self.form = QVBoxLayout(self.content)
        self.form.setContentsMargins(10, 6, 10, 10)
        self.form.setSpacing(COMPACT.section_gap)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("providerSectionDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(bool(description))
        self.form.addWidget(self.description_label)
        root.addWidget(self.content)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self.header.setArrowType(Qt.NoArrow)
        self.header.setIcon(action_icon("chevron-down" if expanded else "chevron-right", size=14))
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
