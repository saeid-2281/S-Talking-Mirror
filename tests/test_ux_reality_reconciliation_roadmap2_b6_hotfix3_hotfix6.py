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


def test_hotfix6_passive_structural_labels_are_transparent() -> None:
    style = manual_visual_acceptance_stylesheet(is_dark=True)

    assert "QFrame#workspaceHero QLabel" in style
    assert "QFrame#projectContextStrip QLabel" in style
    assert "QFrame#metricsStrip QLabel" in style
    assert "QDialog#providerAccountsDialog QLabel" in style
    assert "background:transparent" in style


def test_hotfix6_provider_accounts_table_uses_soft_professional_surfaces() -> None:
    palette = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    style = manual_visual_acceptance_stylesheet(is_dark=True)

    assert "QTableWidget#providerProfilesTable" in style
    assert "QHeaderView#providerProfilesHeader::section" in style
    assert f"background:{palette.surface}" in style
    assert f"alternate-background-color:{palette.surface_secondary}" in style
    assert f"border-left:2px solid {palette.primary}" in style
    assert all(color.upper() not in style.upper() for color in DARK_THEME_LEGACY_SURFACE_COLORS)


def test_hotfix6_provider_accounts_runtime_hosts_are_named_for_final_qss() -> None:
    source = (ROOT / "app" / "gui" / "dialogs" / "provider_accounts_dialog.py").read_text(
        encoding="utf-8"
    )

    assert 'accounts_page.setObjectName("providerAccountsAccountsPage")' in source
    assert 'self.stack.setObjectName("providerAccountsTableStack")' in source
    assert 'self.empty_state.setObjectName("providerAccountsEmptyState")' in source
    assert 'self.table.horizontalHeader().setObjectName("providerProfilesHeader")' in source


def test_hotfix6_primary_actions_use_selected_soft_professional_primary() -> None:
    light = palette_for(is_dark=False, concept_key=ACTIVE_CONCEPT)
    dark = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    light_style = manual_visual_acceptance_stylesheet(is_dark=False)
    dark_style = manual_visual_acceptance_stylesheet(is_dark=True)

    assert "QPushButton[primary=\"true\"]" in light_style
    assert "QPushButton#professionalEmptyStatePrimary" in light_style
    assert f"background:{light.primary}" in light_style
    assert f"background:{dark.primary}" in dark_style

    # Block comments are non-painting QSS text. Hotfix 7 documents the legacy
    # token inside a comment, so inspect only effective declarations/selectors.
    declarations = re.sub(r"/\*.*?\*/", "", light_style, flags=re.S)
    assert "#2563EB" not in declarations.upper()


def test_hotfix6_pixel_certifier_rejects_legacy_navy_and_primary_leakage() -> None:
    source = (
        ROOT / "scripts" / "certify_ux_reconciliation_roadmap2_b6_hotfix3.py"
    ).read_text(encoding="utf-8")

    assert "LEGACY_DARK_STRUCTURAL_RGB" in source
    assert "LEGACY_LIGHT_PRIMARY_RGB" in source
    assert "dark_main_legacy_navy_below_one_percent" in source
    assert "provider_accounts_legacy_navy_below_one_percent" in source
    assert "light_legacy_primary_blue_below_point_two_percent" in source
    assert '"visual_color_audit"' in source


def test_hotfix6_manual_acceptance_layer_is_last_and_presentation_only() -> None:
    palette = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    style = theme_accessibility_stylesheet(is_dark=True)
    marker = "Roadmap 2 B6 Hotfix 3 Hotfix 6"

    assert marker in style
    assert style.rfind(marker) > style.rfind("Roadmap 2 B6 Hotfix 3 — UX Reality Reconciliation")
    assert style.rfind(marker) > style.rfind("Roadmap 2 B6 Hotfix 2")
    assert f"background:{palette.surface}" in style[style.rfind(marker) :]
    assert not any(
        token in manual_visual_acceptance_stylesheet(is_dark=True)
        for token in (
            "start_generation(",
            "run_preflight(",
            "set_active(",
            "setCurrentText(",
            "activate_failover",
        )
    )
