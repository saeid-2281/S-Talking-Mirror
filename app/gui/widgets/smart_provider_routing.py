from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.models.smart_provider_routing import SmartProviderRoutingState


class SmartProviderRoutingCard(QFrame):
    """Explicit provider-routing recommendation surface."""

    actionRequested = Signal(str)
    preferenceChanged = Signal(str)

    PREFERENCES = (
        ("Balanced", "balanced"),
        ("Privacy first", "privacy"),
        ("Lowest provider cost", "lowest_cost"),
        ("Cloud first", "cloud_first"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Reuse the Phase 90 visual contract without adding another theme layer.
        self.setObjectName("providerIntelligenceCard")
        self.setAccessibleName("Smart provider routing")
        self._state: SmartProviderRoutingState | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(11, 10, 11, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title = QLabel("Smart routing")
        title.setObjectName("providerOverviewName")
        subtitle = QLabel("Recommendation only · never switches during a run")
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

        preference_row = QHBoxLayout()
        preference_label = QLabel("Preference")
        preference_label.setObjectName("providerOverviewCaption")
        self.preference = QComboBox()
        self.preference.setAccessibleName("Smart provider routing preference")
        for label, code in self.PREFERENCES:
            self.preference.addItem(label, code)
        self.preference.currentIndexChanged.connect(self._preference_changed)
        preference_row.addWidget(preference_label)
        preference_row.addWidget(self.preference, 1)
        root.addLayout(preference_row)

        self.route_label = QLabel("Stay on current provider")
        self.route_label.setObjectName("providerNextStep")
        self.route_label.setWordWrap(True)
        root.addWidget(self.route_label)

        self.current_label = QLabel("Current: —")
        self.current_label.setObjectName("providerOverviewValue")
        self.current_label.setWordWrap(True)
        self.piper_label = QLabel("Piper: —")
        self.piper_label.setObjectName("providerOverviewValue")
        self.piper_label.setWordWrap(True)
        root.addWidget(self.current_label)
        root.addWidget(self.piper_label)

        self.reason_label = QLabel("Routing recommendation will appear here.")
        self.reason_label.setObjectName("providerNextStep")
        self.reason_label.setWordWrap(True)
        root.addWidget(self.reason_label)

        actions = QHBoxLayout()
        self.primary_action = QPushButton("Current route is best")
        self.primary_action.setObjectName("primaryQuietButton")
        self.primary_action.setIcon(action_icon("provider.accounts"))
        self.primary_action.clicked.connect(lambda: self.actionRequested.emit("apply"))
        self.offline_action = QPushButton("Offline engines")
        self.offline_action.setObjectName("secondaryQuietButton")
        self.offline_action.setIcon(action_icon("settings"))
        self.offline_action.clicked.connect(lambda: self.actionRequested.emit("offline-engines"))
        actions.addWidget(self.primary_action, 1)
        actions.addWidget(self.offline_action)
        root.addLayout(actions)

    @property
    def state(self) -> SmartProviderRoutingState | None:
        return self._state

    def set_preference(self, value: str) -> None:
        index = self.preference.findData(value)
        if index < 0:
            index = self.preference.findData("balanced")
        self.preference.blockSignals(True)
        self.preference.setCurrentIndex(max(0, index))
        self.preference.blockSignals(False)

    def set_state(self, state: SmartProviderRoutingState) -> None:
        self._state = state
        self.set_preference(state.preference)
        self.status_badge.setText("Switch suggested" if state.switch_required else "Route ready")
        self._set_tone(self.status_badge, state.tone)
        self.route_label.setText(state.route_summary)
        current = state.current_candidate
        piper = state.piper_candidate
        self.current_label.setText(
            f"Current · {current.status} · {current.cost_text}"
            + (f" · quota short {current.quota_shortfall:,}" if current.quota_shortfall else "")
        )
        self._set_tone(self.current_label, "success" if current.ready else "error")
        self.piper_label.setText(f"Piper · {piper.status} · {piper.cost_text}")
        self._set_tone(self.piper_label, "success" if piper.ready else "warning")
        self.reason_label.setText(state.recommendation)
        self.primary_action.setText(state.action_label)
        self.primary_action.setEnabled(state.action_enabled)
        self.setAccessibleDescription(
            f"{state.route_summary}. {state.recommendation}. "
            "Provider changes are recommendation-only and never automatic during generation."
        )

    @staticmethod
    def _set_tone(widget: QWidget, tone: str) -> None:
        widget.setProperty("tone", tone or "neutral")
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _preference_changed(self) -> None:
        self.preferenceChanged.emit(str(self.preference.currentData() or "balanced"))
