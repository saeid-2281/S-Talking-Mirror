from __future__ import annotations

import re
from pathlib import Path

from app.gui.theme_accessibility_v2 import (
    DARK_THEME_LEGACY_SURFACE_COLORS,
    manual_visual_acceptance_stylesheet,
    theme_accessibility_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


ROOT = Path(__file__).resolve().parents[1]
MARKER = "Roadmap 2 B6 Hotfix 3 Hotfix 7"


def _hotfix7_tail(*, is_dark: bool) -> str:
    style = manual_visual_acceptance_stylesheet(is_dark=is_dark)
    marker_index = style.index(MARKER)
    return style[marker_index:]


def test_hotfix7_main_shell_structural_hosts_use_selected_concept_surfaces() -> None:
    palette = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    tail = _hotfix7_tail(is_dark=True)

    for selector in (
        "QFrame#metricPill",
        "QFrame#generationActionBar",
        "QFrame#providerPanelHeader",
        "QFrame#providerOverviewCard",
        "QFrame#providerIntelligenceCard",
        "QTabWidget#activityTabs::pane",
        "QStatusBar",
    ):
        assert selector in tail
    assert f"background:{palette.surface}" in tail
    assert f"background:{palette.surface_secondary}" in tail
    assert all(color.upper() not in tail.upper() for color in DARK_THEME_LEGACY_SURFACE_COLORS)


def test_hotfix7_provider_summary_children_stop_repainting_legacy_base() -> None:
    palette = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    tail = _hotfix7_tail(is_dark=True)

    assert "QFrame#providerOverviewCard QLabel" in tail
    assert "QFrame#providerIntelligenceCard QLabel" in tail
    assert "QLabel#providerOverviewIcon" in tail
    assert "QLabel#providerCapabilityBadge" in tail
    assert "QLabel#providerNextStep" in tail
    assert f"background:{palette.surface_secondary}" in tail
    assert "background:transparent" in tail


def test_hotfix7_activity_and_status_chrome_are_semantic_not_legacy_window() -> None:
    palette = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    tail = _hotfix7_tail(is_dark=True)

    assert "QWidget#activityWorkspace" in tail
    assert "QTabWidget#activityWorkspace::pane" in tail
    assert "QStatusBar QLabel" in tail
    assert f"background:{palette.canvas}" in tail
    assert f"border-top:1px solid {palette.border}" in tail


def test_hotfix7_high_specificity_primary_actions_outrank_historical_blue() -> None:
    palette = palette_for(is_dark=False, concept_key=ACTIVE_CONCEPT)
    tail = _hotfix7_tail(is_dark=False)

    for selector in (
        'QPushButton#queuePrimaryAction',
        'QPushButton#queueInspectorAction[primary="true"]',
        'QPushButton#sourcesActionButton[primary="true"]',
        'QPushButton#monitorPrimaryAction',
        'QPushButton#audioPrimaryAction',
    ):
        assert selector in tail
    assert f"background:{palette.primary}" in tail
    assert f"background:{palette.primary_hover}" in tail

    # QSS comments are non-painting text. The regression contract must inspect
    # declarations/selectors, not fail because a diagnostic comment names the
    # historical color being replaced.
    declarations = re.sub(r"/\*.*?\*/", "", tail, flags=re.S)
    assert "#2563EB" not in declarations.upper()


def test_hotfix7_certifier_reports_per_color_share_and_bounding_boxes() -> None:
    source = (
        ROOT / "scripts" / "certify_ux_reconciliation_roadmap2_b6_hotfix3.py"
    ).read_text(encoding="utf-8")

    assert "def _audit_exact_colors(" in source
    assert '"per_color"' in source
    assert '"bbox"' in source
    assert '"diagnostics"' in source
    assert '"dark_main"' in source
    assert '"light_main_primary"' in source
    assert '"dark_legacy_structural_max": 0.01' in source
    assert '"light_legacy_primary_max": 0.002' in source


def test_hotfix7_layer_is_last_and_remains_presentation_only() -> None:
    style = theme_accessibility_stylesheet(is_dark=True)
    tail = _hotfix7_tail(is_dark=True)

    assert style.rfind(MARKER) > style.rfind("Roadmap 2 B6 Hotfix 3 Hotfix 6")
    assert style.rfind(MARKER) > style.rfind("Roadmap 2 B6 Hotfix 2")
    assert not any(
        token in tail
        for token in (
            "start_generation(",
            "run_preflight(",
            "set_active(",
            "setCurrentText(",
            "activate_failover",
            "api_key_for(",
        )
    )
