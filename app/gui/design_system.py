"""Shared visual tokens and density metrics for S Talking desktop UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DensityMetrics:
    control_height: int
    icon_button: int
    row_height: int
    section_gap: int
    panel_padding: int
    corner_radius: int


COMPACT = DensityMetrics(
    control_height=34,
    icon_button=34,
    row_height=32,
    section_gap=8,
    panel_padding=10,
    corner_radius=7,
)

COMFORTABLE = DensityMetrics(
    control_height=38,
    icon_button=38,
    row_height=36,
    section_gap=12,
    panel_padding=14,
    corner_radius=9,
)

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "2xl": 32,
}

TYPE_SCALE = {
    "caption": 11,
    "body": 13,
    "label": 12,
    "section": 14,
    "title": 18,
    "display": 22,
}
