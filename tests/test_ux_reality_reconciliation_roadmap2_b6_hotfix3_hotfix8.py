from __future__ import annotations

import re

from PySide6.QtGui import QPalette

from app.gui.theme import DARK_TOKENS, GRAPHITE_STYLE, LIGHT_STYLE, ThemeManager
from app.gui.theme_accessibility_v2 import DARK_THEME_LEGACY_SURFACE_COLORS
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


def _without_comments(style: str) -> str:
    return re.sub(r"/\*.*?\*/", "", style, flags=re.DOTALL)


def test_hotfix8_preserves_historical_dark_token_and_qpalette_contract() -> None:
    manager = ThemeManager()
    tokens = manager.tokens("Dark")
    palette = manager.palette("Dark")

    assert tokens["app"] == "#0B1220"
    assert tokens is DARK_TOKENS
    assert palette.color(QPalette.ColorRole.Window).name().upper() == "#0B1220"
    assert palette.color(QPalette.ColorRole.Base).name().upper() == DARK_TOKENS["input"]


def test_hotfix8_dark_stylesheet_projects_all_audited_legacy_surface_literals() -> None:
    style = _without_comments(ThemeManager().stylesheet("Dark")).upper()

    for legacy in DARK_THEME_LEGACY_SURFACE_COLORS:
        assert legacy.upper() not in style


def test_hotfix8_dark_stylesheet_projects_legacy_background_palette_roles() -> None:
    style = ThemeManager().stylesheet("Dark")

    for role in (
        "palette(window)",
        "palette(base)",
        "palette(alternate-base)",
        "palette(button)",
        "palette(midlight)",
    ):
        assert role not in style
    # Historical selected-text semantics stay palette-driven for compatibility.
    assert "palette(highlighted-text)" in style


def test_hotfix8_dark_projection_uses_selected_soft_professional_surface_family() -> None:
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    style = ThemeManager().stylesheet("Dark")

    assert f"QWidget{{background:{semantic.canvas}" in style
    assert semantic.surface in style
    assert semantic.surface_secondary in style
    assert semantic.border in style
    assert semantic.border_strong in style


def test_hotfix8_existing_light_and_graphite_styles_remain_exactly_unchanged() -> None:
    manager = ThemeManager()

    assert manager.stylesheet("Light") == LIGHT_STYLE
    assert manager.stylesheet("Graphite") == GRAPHITE_STYLE
    assert "#F4F7FB" in manager.stylesheet("Light")
    assert "#2563EB" in manager.stylesheet("Light")
