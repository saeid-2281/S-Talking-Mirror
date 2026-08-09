from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
from app.models.generation_journey import GenerationJourneyState


_STATUS_SYMBOL = {
    "success": "✓",
    "warning": "!",
    "error": "×",
    "info": "○",
    "neutral": "○",
    "running": "●",
}


class GenerationJourneyWidget(QFrame):
    """Compact, guided path from source preparation to a guarded launch."""

    actionRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("generationJourney")
        self.setAccessibleName("Generation workflow")
        self._state: GenerationJourneyState | None = None
        self._compact = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(5)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)

        self.headline = QLabel("Prepare your source")
        self.headline.setObjectName("workspaceTitle")
        self.summary = QLabel("Generation UX 2.0 will show the next useful action here.")
        self.summary.setObjectName("workspaceSubtitle")
        self.summary.setWordWrap(False)
        self.summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_box.addWidget(self.headline)
        title_box.addWidget(self.summary)
        header.addLayout(title_box, 1)

        self.primary_action = QPushButton("Prepare text")
        self.primary_action.setObjectName("generationPrimaryAction")
        self.primary_action.setIcon(action_icon("generation.preflight"))
        self.primary_action.setMinimumHeight(32)
        self.primary_action.setAccessibleName("Next generation workflow action")
        self.primary_action.clicked.connect(self._emit_primary)
        header.addWidget(self.primary_action)
        root.addLayout(header)

        self.steps_host = QFrame()
        self.steps_host.setObjectName("generationJourneySteps")
        steps_layout = QHBoxLayout(self.steps_host)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(5)

        self.step_buttons: dict[str, QPushButton] = {}
        for index, (code, label) in enumerate(
            (
                ("source", "Source"),
                ("provider", "Provider"),
                ("voice", "Voice"),
                ("scope", "Scope"),
                ("preflight", "Preflight"),
            ),
            start=1,
        ):
            button = QPushButton(f"{index}  {label}")
            button.setObjectName("workspaceSecondaryAction")
            button.setProperty("journeyStep", code)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(30)
            button.clicked.connect(
                lambda _checked=False, step_code=code: self._emit_step(step_code)
            )
            self.step_buttons[code] = button
            steps_layout.addWidget(button, 1)

        root.addWidget(self.steps_host)
        self.setMaximumHeight(104)

    @property
    def state(self) -> GenerationJourneyState | None:
        return self._state

    def set_state(self, state: GenerationJourneyState) -> None:
        if state == self._state:
            return
        self._state = state
        self.headline.setText(state.headline)
        self.summary.setText(state.summary)
        self.summary.setToolTip(state.summary)

        for index, step in enumerate(state.steps, start=1):
            button = self.step_buttons[step.code]
            symbol = _STATUS_SYMBOL.get(step.tone, "○")
            button.setText(f"{symbol} {index}  {step.label} · {step.status}")
            button.setToolTip(step.detail)
            button.setAccessibleName(
                f"Generation step {index}: {step.label}, {step.status}"
            )
            button.setAccessibleDescription(step.detail)
            button.setProperty("tone", step.tone)
            button.style().unpolish(button)
            button.style().polish(button)

        self.primary_action.setText(state.next_action_label)
        self.primary_action.setEnabled(bool(state.next_action_code))
        self.primary_action.setToolTip(state.summary)
        self.primary_action.setAccessibleDescription(state.summary)
        self.primary_action.setIcon(
            action_icon("generation.start" if state.ready_to_start else "generation.preflight")
        )

    def set_compact_mode(self, compact: bool) -> None:
        """Yield all vertical space to the queue in compact/focus presets.

        The journey remains available on demand through the Generation Workflow
        action/shortcut.  Hiding the whole strip here preserves the established
        compact-workspace contract that the loaded queue dominates short screens.
        """
        self._compact = bool(compact)
        self.steps_host.setVisible(not self._compact)
        self.summary.setVisible(not self._compact)
        self.setMaximumHeight(52 if self._compact else 104)
        self.setMinimumHeight(0)
        self.setVisible(not self._compact)

    def focus_primary_action(self) -> None:
        self.primary_action.setFocus(Qt.ShortcutFocusReason)

    def _emit_primary(self) -> None:
        if self._state and self._state.next_action_code:
            self.actionRequested.emit(self._state.next_action_code)

    def _emit_step(self, code: str) -> None:
        if not self._state:
            return
        step = next((item for item in self._state.steps if item.code == code), None)
        if step is not None:
            self.actionRequested.emit(step.action_code)
