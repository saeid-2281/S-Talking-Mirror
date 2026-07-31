from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceProfile:
    """Declarative desktop workspace arrangement."""

    name: str
    left_dock_visible: bool
    right_dock_visible: bool
    activity_visible: bool
    activity_height: int
    left_dock_width: int
    right_dock_width: int
    right_tab: int = 0
    toolbar_visible: bool = True
    description: str = ""
