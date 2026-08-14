from __future__ import annotations

import ast
from pathlib import Path

from app.gui.theme import DARK_TOKENS, LIGHT_TOKENS, STATUS_COLORS
from app.gui.visual_design_system_v2 import (
    ACTIVE_CONCEPT,
    COMPONENTS,
    CONCEPTS,
    ICONS,
    MODERN_TECHNICAL_DARK,
    MODERN_TECHNICAL_LIGHT,
    SPACING,
    TYPOGRAPHY,
    UI_INVENTORY,
    concept_preview_stylesheet,
    visual_system_stylesheet,
)

ROOT = Path(__file__).resolve().parents[1]


def test_a8_defines_exactly_three_real_visual_concepts() -> None:
    assert tuple(CONCEPTS) == ("precision", "soft_professional", "modern_technical")
    assert [CONCEPTS[key].name for key in CONCEPTS] == [
        "Precision",
        "Soft Professional",
        "Modern Technical",
    ]


def test_a8_selects_modern_technical_as_product_direction() -> None:
    assert ACTIVE_CONCEPT == "modern_technical"
    assert "production queues" in CONCEPTS[ACTIVE_CONCEPT].description.lower()


def test_a8_modern_technical_light_semantic_tokens_match_product_contract() -> None:
    palette = MODERN_TECHNICAL_LIGHT
    assert palette.canvas == "#F6F7F9"
    assert palette.surface == "#FFFFFF"
    assert palette.surface_secondary == "#F1F3F5"
    assert palette.border == "#E2E5E9"
    assert palette.text_primary == "#171A1F"
    assert palette.text_secondary == "#606772"
    assert palette.text_muted == "#8A929E"
    assert palette.primary == "#4768E5"
    assert palette.primary_hover == "#3D5BCB"
    assert palette.success == "#21865A"
    assert palette.warning == "#C47B18"
    assert palette.danger == "#C84A4A"
    assert palette.info == "#3E78C5"


def test_a8_defines_complete_dark_semantic_counterpart() -> None:
    assert MODERN_TECHNICAL_DARK.canvas.startswith("#")
    assert MODERN_TECHNICAL_DARK.surface != MODERN_TECHNICAL_LIGHT.surface
    assert MODERN_TECHNICAL_DARK.text_primary != MODERN_TECHNICAL_LIGHT.text_primary
    assert MODERN_TECHNICAL_DARK.primary != MODERN_TECHNICAL_LIGHT.primary
    assert MODERN_TECHNICAL_DARK.focus_ring


def test_a8_formalizes_type_spacing_icon_and_compatibility_metrics() -> None:
    assert (TYPOGRAPHY.caption, TYPOGRAPHY.body, TYPOGRAPHY.section, TYPOGRAPHY.title) == (11, 13, 14, 18)
    assert (SPACING.xs, SPACING.sm, SPACING.md, SPACING.lg, SPACING.xl) == (4, 8, 12, 16, 24)
    assert (ICONS.compact, ICONS.standard, ICONS.prominent, ICONS.feature) == (16, 20, 24, 32)
    assert COMPONENTS.toolbar_height <= 42
    assert COMPONENTS.generation_action_bar_height <= 44
    assert COMPONENTS.queue_row_compact_height == 30
    assert COMPONENTS.queue_row_comfortable_height == 32


def test_a8_inventory_maps_actual_s_talking_product_surfaces() -> None:
    areas = {item.area for item in UI_INVENTORY}
    assert {
        "Application shell",
        "Project context",
        "Queue metrics",
        "Provider / Sources",
        "Queue command center",
        "Queue table",
        "Selected-row inspector",
        "Generation monitor",
        "Text Studio / Sources",
        "Preflight / launch",
        "Operations / reports",
        "Theme / accessibility",
    }.issubset(areas)


def test_a8_application_overlay_targets_real_s_talking_objects_without_geometry_takeover() -> None:
    qss = visual_system_stylesheet(is_dark=False)
    for selector in (
        "QToolBar#mainToolbar",
        "#projectContextBar",
        "#metricsStrip",
        "#providerPanel",
        "#queueWorkspace",
        "#sourcesWorkspaceHeader",
        "QTableView",
        "QStatusBar",
    ):
        assert selector in qss
    lowered = qss.lower()
    for forbidden in ("min-width:", "max-width:", "min-height:", "max-height:", "position:"):
        assert forbidden not in lowered


def test_a8_overlay_preserves_theme_manager_mainwindow_palette_authority() -> None:
    qss = visual_system_stylesheet(is_dark=False)
    assert "QMainWindow" not in qss
    assert "QDialog" in qss


def test_a8_each_concept_has_a_visually_distinct_real_specimen_contract() -> None:
    previews = {key: concept_preview_stylesheet(key) for key in CONCEPTS}
    assert len(set(previews.values())) == 3
    for qss in previews.values():
        assert "#specimenToolbar" in qss
        assert "#specimenProvider" in qss
        assert "#specimenQueue" in qss
        assert "#specimenPrimary" in qss


def test_a8_preserves_legacy_theme_contract_instead_of_replacing_theme_module() -> None:
    assert DARK_TOKENS["canvas"] == "#0A0F1C"
    assert LIGHT_TOKENS["canvas"] == "#F3F6FA"
    assert STATUS_COLORS["skipped"] == "#94A3B8"


def test_a8_mainwindow_appends_semantic_overlay_and_exposes_reference_action() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "visual_system_stylesheet" in source
    assert "QPalette.Window" in source
    assert "Visual Design System 2.0…" in source
    assert "Ctrl+Alt+8" in source
    assert "View: Visual Design System 2.0" in source
    assert "def open_visual_design_system" in source


def test_a8_reference_dialog_is_read_only_and_has_no_generation_authority() -> None:
    path = ROOT / "app/gui/dialogs/visual_design_system_dialog.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert tree is not None
    assert "designConceptTabs" in source
    assert "visualInventoryTable" in source
    assert "selectedConceptBadge" in source
    assert "QDialogButtonBox.Close" in source
    for forbidden in (
        ".start(",
        "run_preflight(",
        "generation_controller",
        "setCurrentText(",
        "set_language",
        "smart_routing",
    ):
        assert forbidden not in source


def test_a8_dialog_renders_inventory_and_all_three_concept_pages(qt_app) -> None:
    from app.gui.dialogs.visual_design_system_dialog import VisualDesignSystemDialog

    dialog = VisualDesignSystemDialog()
    try:
        assert dialog.objectName() == "visualDesignSystemDialog"
        assert dialog.tabs.count() == 4
        assert dialog.tabs.tabText(0) == "Visual inventory"
        assert dialog.tabs.tabText(1) == "Precision"
        assert dialog.tabs.tabText(2) == "Soft Professional"
        assert "Modern Technical" in dialog.tabs.tabText(3)
        assert "Selected" in dialog.selected_badge.text()
        assert dialog.inventory_table.rowCount() == len(UI_INVENTORY)
    finally:
        dialog.close()
