from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.models.provider_intelligence import ProviderIntelligenceState


class ProviderIntelligenceCard(QFrame):
    """Compact decision surface for provider/model/voice selection."""

    actionRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("providerIntelligenceCard")
        self.setAccessibleName("Provider intelligence")
        self._state: ProviderIntelligenceState | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(11, 10, 11, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title = QLabel("Provider intelligence")
        title.setObjectName("providerOverviewName")
        subtitle = QLabel("Compatibility, quota and cost before preflight")
        subtitle.setObjectName("providerOverviewMode")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        self.status_badge = QLabel("Review")
        self.status_badge.setObjectName("providerReadinessBadge")
        self.status_badge.setProperty("tone", "neutral")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        header.addWidget(self.status_badge, 0, Qt.AlignTop)
        root.addLayout(header)

        self.selection_label = QLabel("Model / voice: —")
        self.selection_label.setObjectName("providerNextStep")
        self.selection_label.setWordWrap(True)
        root.addWidget(self.selection_label)

        facts = QGridLayout()
        facts.setContentsMargins(0, 0, 0, 0)
        facts.setHorizontalSpacing(8)
        facts.setVerticalSpacing(3)
        self.compatibility_label = self._add_fact(facts, 0, "Fit")
        self.quota_label = self._add_fact(facts, 1, "Quota")
        self.batch_label = self._add_fact(facts, 2, "Batch")
        self.cost_label = self._add_fact(facts, 3, "Estimate")
        facts.setColumnStretch(1, 1)
        root.addLayout(facts)

        self.recommendation_label = QLabel("Provider intelligence will appear here.")
        self.recommendation_label.setObjectName("providerNextStep")
        self.recommendation_label.setWordWrap(True)
        root.addWidget(self.recommendation_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.primary_action = QPushButton("Review provider")
        self.primary_action.setObjectName("primaryQuietButton")
        self.primary_action.setIcon(action_icon("generation.preflight"))
        self.primary_action.clicked.connect(self._emit_primary)
        self.browse_action = QPushButton("Voices")
        self.browse_action.setObjectName("secondaryQuietButton")
        self.browse_action.setIcon(action_icon("provider.browse_voices"))
        self.browse_action.clicked.connect(lambda: self.actionRequested.emit("browse-voices"))
        actions.addWidget(self.primary_action, 1)
        actions.addWidget(self.browse_action)
        root.addLayout(actions)

    @staticmethod
    def _add_fact(layout: QGridLayout, row: int, caption: str) -> QLabel:
        caption_label = QLabel(caption)
        caption_label.setObjectName("providerOverviewCaption")
        value = QLabel("—")
        value.setObjectName("providerOverviewValue")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(caption_label, row, 0, Qt.AlignTop)
        layout.addWidget(value, row, 1)
        return value

    @property
    def state(self) -> ProviderIntelligenceState | None:
        return self._state

    def set_state(self, state: ProviderIntelligenceState) -> None:
        if state == self._state:
            return
        self._state = state
        self.status_badge.setText(state.status)
        self._set_tone(self.status_badge, state.tone)
        self.selection_label.setText(f"{state.provider_name} · {state.selection_summary}")
        self.compatibility_label.setText(state.compatibility_text)
        self._set_tone(self.compatibility_label, state.compatibility_tone)
        self.quota_label.setText(state.quota_text)
        self._set_tone(self.quota_label, state.quota_tone)
        self.batch_label.setText(state.batch_text)
        self.cost_label.setText(state.cost_text)
        self.recommendation_label.setText(state.recommendation)
        self.primary_action.setText(state.primary_action_label)
        self.primary_action.setEnabled(bool(state.primary_action_code))
        self.primary_action.setIcon(
            action_icon(
                "general.success"
                if state.primary_action_code == "apply-suggestion"
                else "generation.preflight"
            )
        )
        self.setAccessibleDescription(
            f"{state.provider_name}. {state.status}. {state.compatibility_text}. "
            f"Quota: {state.quota_text}. Estimate: {state.cost_text}. {state.recommendation}"
        )

    @staticmethod
    def _set_tone(widget: QWidget, tone: str) -> None:
        widget.setProperty("tone", tone or "neutral")
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _emit_primary(self) -> None:
        if self._state and self._state.primary_action_code:
            self.actionRequested.emit(self._state.primary_action_code)
