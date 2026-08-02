from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceProfile:
    """Declarative desktop workspace arrangement and presentation mode."""

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
    density: str = "comfortable"
    header_mode: str = "expanded"
    metrics_visible: bool = True
