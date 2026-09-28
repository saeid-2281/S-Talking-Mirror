from __future__ import annotations

import inspect

from app.gui.main import MainWindow


def _ordered(source: str, *needles: str) -> bool:
    position = -1
    for needle in needles:
        next_position = source.find(needle, position + 1)
        if next_position < 0:
            return False
        position = next_position
    return True


def test_stage3b3_live_theme_switch_coalesces_repaint_burst() -> None:
    source = inspect.getsource(MainWindow.apply_theme)

    assert "application.styleSheet()!=stylesheet" in source
    assert "application.topLevelWidgets()" in source
    assert _ordered(
        source,
        "application.setPalette(palette)",
        "top_level.setUpdatesEnabled(False)",
        "application.setStyleSheet(stylesheet)",
        "top_level.setUpdatesEnabled(True)",
        "refresh_icons(self)",
    )


def test_stage3b3_guard_restores_updates_even_if_qt_restyle_raises() -> None:
    source = inspect.getsource(MainWindow.apply_theme)

    assert "guarded_updates=[]" in source
    assert "finally:" in source
    assert "for top_level in reversed(guarded_updates):" in source
    assert "except RuntimeError:" in source


def test_stage3b3_interface_preference_restyle_uses_same_repaint_guard() -> None:
    source = inspect.getsource(MainWindow.apply_interface_preferences)

    assert "if properties_changed:" in source
    assert "application.topLevelWidgets()" in source
    assert _ordered(
        source,
        "application.setPalette(palette)",
        "top_level.setUpdatesEnabled(False)",
        "application.setStyleSheet(stylesheet)",
        "top_level.setUpdatesEnabled(True)",
    )


def test_stage3b3_keeps_application_stylesheet_and_palette_authority() -> None:
    source = inspect.getsource(MainWindow.apply_theme)

    assert "application.setPalette(palette)" in source
    assert "application.setStyleSheet(stylesheet)" in source
    assert "refresh_icons(self)" in source
    assert "theme_accessibility_modernizer.apply_theme" in source
    assert "self.theme_manager.save(name)" in source
