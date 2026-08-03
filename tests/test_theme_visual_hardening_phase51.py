from __future__ import annotations

import inspect

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from app.gui.icons import icon, refresh_icons
from app.gui.theme import (
    DARK_TOKENS,
    GRAPHITE_TOKENS,
    LIGHT_TOKENS,
    ThemeManager,
    _build_palette,
)
from app.gui.widgets.application_shell import GenerationStatusStrip
from app.gui.widgets.provider_controls import ProviderSection


def test_graphite_theme_preserves_brand_contracts() -> None:
    assert DARK_TOKENS["canvas"] == "#0A0F1C"
    assert LIGHT_TOKENS["canvas"] == "#F3F6FA"
    assert GRAPHITE_TOKENS["canvas"] == "#16181C"
    assert GRAPHITE_TOKENS["app"] != DARK_TOKENS["app"]
    assert GRAPHITE_TOKENS["selected_text"] == "#FFFFFF"


def test_theme_manager_exposes_graphite_without_changing_system_resolution(qt_app) -> None:  # noqa: ANN001
    manager = ThemeManager()
    assert manager.available_themes() == ("Dark", "Graphite", "Light", "System")
    assert manager.effective_name("Graphite") == "Graphite"
    assert manager.tokens("Graphite") is GRAPHITE_TOKENS
    assert manager.effective_name("unknown") == "Dark"


def test_all_palettes_use_explicit_readable_selected_text() -> None:
    for tokens in (DARK_TOKENS, GRAPHITE_TOKENS, LIGHT_TOKENS):
        palette = _build_palette(tokens)
        assert palette.color(QPalette.Highlight).name().upper() == tokens["selected_row"].upper()
        assert palette.color(QPalette.HighlightedText).name().upper() == tokens["selected_text"].upper()
        assert palette.color(QPalette.HighlightedText) != palette.color(QPalette.Highlight)


def test_stylesheet_hardens_table_selection_and_generation_alignment() -> None:
    manager = ThemeManager()
    for name in ("Dark", "Graphite", "Light"):
        style = manager.stylesheet(name)
        assert "QAbstractItemView::item:selected" in style
        assert "color: palette(highlighted-text);" in style
        assert "QFrame#generationActionBar QPushButton" in style
        assert "QToolButton#providerSectionHeader" in style


def test_registered_icons_are_recolored_after_theme_change(qt_app) -> None:  # noqa: ANN001
    qt_app.setPalette(_build_palette(DARK_TOKENS))
    button = QPushButton()
    button.setIcon(icon("settings"))
    dark_key = button.icon().cacheKey()

    qt_app.setPalette(_build_palette(LIGHT_TOKENS))
    refresh_icons()
    light_key = button.icon().cacheKey()

    assert not button.icon().isNull()
    assert light_key != dark_key


def test_provider_disclosure_uses_centered_theme_icons(qt_app) -> None:  # noqa: ANN001
    section = ProviderSection("Provider account", expanded=True)
    assert section.header.arrowType() == Qt.NoArrow
    assert not section.header.icon().isNull()
    assert section.header.iconSize().width() == 14

    expanded_key = section.header.icon().cacheKey()
    section.set_expanded(False)
    assert section.header.arrowType() == Qt.NoArrow
    assert section.header.icon().cacheKey() != expanded_key


def test_generation_action_buttons_share_one_vertical_geometry(qt_app) -> None:  # noqa: ANN001
    strip = GenerationStatusStrip(
        start=lambda: None,
        pause=lambda: None,
        stop=lambda: None,
        show_preflight=lambda: None,
    )
    buttons = (
        strip.start_button,
        strip.preflight_button,
        strip.pause_button,
        strip.stop_button,
    )
    assert {button.minimumHeight() for button in buttons} == {30}
    assert {button.maximumHeight() for button in buttons} == {30}
    assert strip.maximumHeight() <= 44


def test_release_candidate_uses_canonical_versioned_package_name() -> None:
    from app.services.release_candidate_service import ReleaseCandidateService

    source = inspect.getsource(ReleaseCandidateService.build_candidate)
    assert 'f"S-Talking-{self.version}-portable.zip"' in source
    assert "candidate_dir / package.name" not in source


def test_icon_refresh_tolerates_legacy_actions_list_shadowing_qwidget_method(qt_app) -> None:  # noqa: ANN001
    class LegacyActionsWidget(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.actions: list[QAction] = []

    qt_app.setPalette(_build_palette(DARK_TOKENS))
    widget = LegacyActionsWidget()
    action = QAction(widget)
    action.setIcon(icon("settings"))
    widget.actions.append(action)
    dark_key = action.icon().cacheKey()

    qt_app.setPalette(_build_palette(LIGHT_TOKENS))
    refresh_icons()

    assert not action.icon().isNull()
    assert action.icon().cacheKey() != dark_key

    widget.close()
    widget.deleteLater()


def test_icon_rendering_is_cached_and_refresh_can_be_scoped(qt_app) -> None:  # noqa: ANN001
    qt_app.setPalette(_build_palette(DARK_TOKENS))
    first = icon("settings")
    second = icon("settings")
    assert first.cacheKey() == second.cacheKey()

    root = QWidget()
    layout = QVBoxLayout(root)
    inside = QPushButton(root)
    inside.setIcon(icon("settings"))
    layout.addWidget(inside)

    outside = QPushButton()
    outside.setIcon(icon("settings"))
    inside_dark = inside.icon().cacheKey()
    outside_dark = outside.icon().cacheKey()

    qt_app.setPalette(_build_palette(LIGHT_TOKENS))
    refreshed = refresh_icons(root)

    assert refreshed >= 1
    assert inside.icon().cacheKey() != inside_dark
    assert outside.icon().cacheKey() == outside_dark

    root.close()
    outside.close()


def test_mainwindow_theme_refresh_avoids_global_repolish_and_scans_its_tree() -> None:
    from app.gui.main import MainWindow

    source = inspect.getsource(MainWindow.apply_theme)
    assert "application.styleSheet()!=stylesheet" in source
    assert "refresh_icons(self)" in source
    assert "refresh_icons()" not in source
