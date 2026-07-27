from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpacingScale:
    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32


@dataclass(frozen=True)
class ControlScale:
    compact: int = 34
    comfortable: int = 38
    primary: int = 40
    icon: int = 36
    toolbar: int = 40
    row_compact: int = 32
    row_comfortable: int = 38


@dataclass(frozen=True)
class RadiusScale:
    small: int = 5
    standard: int = 8
    panel: int = 10


@dataclass(frozen=True)
class TypographyScale:
    caption: int = 11
    compact: int = 12
    body: int = 13
    section: int = 14
    page_title: int = 18
    display: int = 22


SPACING = SpacingScale()
CONTROLS = ControlScale()
RADII = RadiusScale()
TYPE = TypographyScale()

DENSITY_COMPACT = "compact"
DENSITY_COMFORTABLE = "comfortable"


def control_height(density: str) -> int:
    return CONTROLS.comfortable if density == DENSITY_COMFORTABLE else CONTROLS.compact


def table_row_height(density: str) -> int:
    return CONTROLS.row_comfortable if density == DENSITY_COMFORTABLE else CONTROLS.row_compact
