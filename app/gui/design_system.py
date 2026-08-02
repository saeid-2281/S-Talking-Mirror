"""Shared visual tokens, density metrics and semantic UI helpers.

The module deliberately contains no Qt imports. Presentation rules can be
validated in isolation and consumed by widgets without coupling business code
to a concrete desktop toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkspaceDensity(StrEnum):
    COMPACT = "compact"
    COMFORTABLE = "comfortable"


class SemanticTone(StrEnum):
    NEUTRAL = "neutral"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    RUNNING = "running"


@dataclass(frozen=True)
class DensityMetrics:
    control_height: int
    icon_button: int
    row_height: int
    section_gap: int
    panel_padding: int
    corner_radius: int
    shell_margin: int
    header_height: int
    metric_height: int


COMPACT = DensityMetrics(
    control_height=34,
    icon_button=34,
    row_height=30,
    section_gap=6,
    panel_padding=9,
    corner_radius=8,
    shell_margin=8,
    header_height=72,
    metric_height=52,
)

COMFORTABLE = DensityMetrics(
    control_height=38,
    icon_button=38,
    # Keep the long-standing 32 px queue-row contract. Comfortable density
    # increases whitespace around the grid instead of inflating every row.
    row_height=32,
    section_gap=10,
    panel_padding=14,
    corner_radius=10,
    shell_margin=12,
    header_height=88,
    metric_height=62,
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


def normalize_density(value: object) -> WorkspaceDensity:
    text = str(value or "").strip().casefold()
    if text == WorkspaceDensity.COMPACT.value:
        return WorkspaceDensity.COMPACT
    return WorkspaceDensity.COMFORTABLE


def density_metrics(value: object) -> DensityMetrics:
    return COMPACT if normalize_density(value) is WorkspaceDensity.COMPACT else COMFORTABLE


def semantic_tone(value: object) -> SemanticTone:
    """Map operational words to stable visual tones.

    The helper accepts enum values and free-form labels because the existing UI
    receives status strings from multiple generations of services.
    """

    text = str(getattr(value, "value", value) or "").strip().casefold()
    if any(token in text for token in ("failed", "error", "blocked", "critical", "missed")):
        return SemanticTone.ERROR
    if any(token in text for token in ("warning", "watch", "at risk", "at_risk", "cooldown")):
        return SemanticTone.WARNING
    if any(token in text for token in ("running", "active", "generating", "paused")):
        return SemanticTone.RUNNING
    if any(token in text for token in ("ready", "completed", "healthy", "success", "closed")):
        return SemanticTone.SUCCESS
    if any(token in text for token in ("info", "pending", "not checked", "not_checked")):
        return SemanticTone.INFO
    return SemanticTone.NEUTRAL
