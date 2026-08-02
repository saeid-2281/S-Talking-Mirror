"""Persistent professional-interface and accessibility preferences.

The model is intentionally Qt-light: it accepts any settings object exposing
``value`` and ``setValue`` so normalization and persistence can be tested
without constructing the full application window.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol


class SettingsLike(Protocol):
    def value(self, key: str, default: object = None) -> object: ...

    def setValue(self, key: str, value: object) -> None: ...

    def sync(self) -> None: ...


class ContrastMode(StrEnum):
    STANDARD = "standard"
    HIGH = "high"


class FocusStyle(StrEnum):
    STANDARD = "standard"
    ENHANCED = "enhanced"


TEXT_SCALES = (100, 110, 125)
SETTINGS_PREFIX = "interface"


def _boolean(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "enabled"}


def normalize_contrast(value: object) -> ContrastMode:
    return ContrastMode.HIGH if str(value or "").strip().casefold() == "high" else ContrastMode.STANDARD


def normalize_focus_style(value: object) -> FocusStyle:
    return FocusStyle.ENHANCED if str(value or "").strip().casefold() == "enhanced" else FocusStyle.STANDARD


def normalize_text_scale(value: object) -> int:
    try:
        numeric = int(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return 100
    return min(TEXT_SCALES, key=lambda candidate: abs(candidate - numeric))


@dataclass(frozen=True)
class InterfacePreferences:
    contrast: ContrastMode = ContrastMode.STANDARD
    text_scale: int = 100
    focus_style: FocusStyle = FocusStyle.STANDARD
    reduce_motion: bool = False
    announce_status: bool = True

    @classmethod
    def defaults(cls) -> "InterfacePreferences":
        return cls()

    @classmethod
    def from_settings(cls, settings: SettingsLike) -> "InterfacePreferences":
        return cls(
            contrast=normalize_contrast(settings.value(f"{SETTINGS_PREFIX}/contrast", "standard")),
            text_scale=normalize_text_scale(settings.value(f"{SETTINGS_PREFIX}/text_scale", 100)),
            focus_style=normalize_focus_style(settings.value(f"{SETTINGS_PREFIX}/focus_style", "standard")),
            reduce_motion=_boolean(settings.value(f"{SETTINGS_PREFIX}/reduce_motion", False)),
            announce_status=_boolean(settings.value(f"{SETTINGS_PREFIX}/announce_status", True), True),
        )

    def normalized(self) -> "InterfacePreferences":
        return replace(
            self,
            contrast=normalize_contrast(self.contrast),
            text_scale=normalize_text_scale(self.text_scale),
            focus_style=normalize_focus_style(self.focus_style),
            reduce_motion=bool(self.reduce_motion),
            announce_status=bool(self.announce_status),
        )

    def save(self, settings: SettingsLike) -> None:
        value = self.normalized()
        settings.setValue(f"{SETTINGS_PREFIX}/contrast", value.contrast.value)
        settings.setValue(f"{SETTINGS_PREFIX}/text_scale", value.text_scale)
        settings.setValue(f"{SETTINGS_PREFIX}/focus_style", value.focus_style.value)
        settings.setValue(f"{SETTINGS_PREFIX}/reduce_motion", value.reduce_motion)
        settings.setValue(f"{SETTINGS_PREFIX}/announce_status", value.announce_status)
        sync = getattr(settings, "sync", None)
        if callable(sync):
            sync()

    def stylesheet_properties(self) -> dict[str, object]:
        value = self.normalized()
        return {
            "contrastMode": value.contrast.value,
            "textScale": str(value.text_scale),
            "focusMode": value.focus_style.value,
            "reduceMotion": "true" if value.reduce_motion else "false",
        }

    def summary(self) -> str:
        value = self.normalized()
        contrast = "High contrast" if value.contrast is ContrastMode.HIGH else "Standard contrast"
        focus = "Enhanced focus" if value.focus_style is FocusStyle.ENHANCED else "Standard focus"
        motion = "Reduced motion" if value.reduce_motion else "Normal motion"
        announcements = "Status announcements on" if value.announce_status else "Status announcements off"
        return f"{contrast} · Text {value.text_scale}% · {focus} · {motion} · {announcements}"
