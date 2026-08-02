from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QWidget


class WorkspaceBreakpoint(StrEnum):
    COMPACT = "compact"
    STANDARD = "standard"
    WIDE = "wide"


@dataclass(frozen=True)
class ResponsiveWorkspaceState:
    mode: WorkspaceBreakpoint
    window_width: int
    window_height: int
    queue_width: int
    left_dock_width: int
    right_dock_width: int
    source_action_columns: int
    toolbar_icon_only: bool
    metrics_compact: bool


def resolve_workspace_state(
    *,
    window_width: int,
    window_height: int,
    queue_width: int,
) -> ResponsiveWorkspaceState:
    """Resolve a stable professional workspace layout for the available space.

    Queue width is considered alongside the top-level window because users can
    manually resize the provider and inspector docks. This prevents the central
    controls from becoming unreadable even on a physically wide monitor.
    """

    width = max(1, int(window_width))
    height = max(1, int(window_height))
    center = max(1, int(queue_width))

    if width < 1080 or center < 520:
        mode = WorkspaceBreakpoint.COMPACT
    elif width < 1560 or center < 900:
        mode = WorkspaceBreakpoint.STANDARD
    else:
        mode = WorkspaceBreakpoint.WIDE

    if mode is WorkspaceBreakpoint.WIDE:
        return ResponsiveWorkspaceState(
            mode=mode,
            window_width=width,
            window_height=height,
            queue_width=center,
            left_dock_width=320,
            right_dock_width=330,
            source_action_columns=3,
            toolbar_icon_only=False,
            metrics_compact=False,
        )
    if mode is WorkspaceBreakpoint.STANDARD:
        return ResponsiveWorkspaceState(
            mode=mode,
            window_width=width,
            window_height=height,
            queue_width=center,
            left_dock_width=290,
            right_dock_width=310,
            source_action_columns=3,
            toolbar_icon_only=False,
            metrics_compact=height < 820,
        )
    return ResponsiveWorkspaceState(
        mode=mode,
        window_width=width,
        window_height=height,
        queue_width=center,
        left_dock_width=270,
        right_dock_width=290,
        source_action_columns=2,
        toolbar_icon_only=True,
        metrics_compact=True,
    )


class ResponsiveWorkspaceCoordinator(QObject):
    """Debounce resize events and publish stable breakpoint transitions.

    Qt can emit a cascade of resize and layout events while controls are moved
    between layouts. Re-applying the responsive layout for every pixel change
    caused a native event-loop recursion on Windows/PySide6. The coordinator
    therefore reacts only when the *presentation signature* changes and guards
    against re-entrant application.
    """

    def __init__(
        self,
        window: QWidget,
        queue_widget: QWidget,
        apply_state: Callable[[ResponsiveWorkspaceState], None],
    ) -> None:
        super().__init__(window)
        self.window = window
        self.queue_widget = queue_widget
        self.apply_state = apply_state
        self._last_state: ResponsiveWorkspaceState | None = None
        self._applying = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self.refresh)
        self.watch(window)
        self.watch(queue_widget)

    @property
    def state(self) -> ResponsiveWorkspaceState | None:
        return self._last_state

    def watch(self, widget: QWidget | None) -> None:
        if widget is not None:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if event.type() in {
            QEvent.Resize,
            QEvent.WindowStateChange,
        }:
            self.schedule()
        return super().eventFilter(watched, event)

    def schedule(self) -> None:
        if not self._applying:
            self._timer.start()

    @staticmethod
    def _presentation_signature(state: ResponsiveWorkspaceState) -> tuple[object, ...]:
        """Return only values that can change widget presentation.

        Exact window and queue dimensions are useful telemetry but must not
        trigger layout mutation while the current breakpoint is unchanged.
        """

        return (
            state.mode,
            state.left_dock_width,
            state.right_dock_width,
            state.source_action_columns,
            state.toolbar_icon_only,
            state.metrics_compact,
        )

    def refresh(self, *, force: bool = False) -> ResponsiveWorkspaceState:
        state = resolve_workspace_state(
            window_width=self.window.width(),
            window_height=self.window.height(),
            queue_width=self.queue_widget.width(),
        )
        previous = self._last_state
        should_apply = (
            force
            or previous is None
            or self._presentation_signature(state)
            != self._presentation_signature(previous)
        )
        self._last_state = state
        if should_apply and not self._applying:
            self._applying = True
            self._timer.stop()
            try:
                self.apply_state(state)
            finally:
                self._applying = False
        return state
