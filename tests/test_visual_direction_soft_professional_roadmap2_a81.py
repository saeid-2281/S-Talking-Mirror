from __future__ import annotations

from pathlib import Path

from app.gui.visual_design_system_v2 import (
    ACTIVE_CONCEPT,
    A9_HANDOFF_PRINCIPLES,
    CONCEPTS,
    MODERN_TECHNICAL_LIGHT,
    SELECTED_DIRECTION_RATIONALE,
    SOFT_PROFESSIONAL_DARK,
    SOFT_PROFESSIONAL_LIGHT,
    concept_preview_stylesheet,
    selected_concept_badge_stylesheet,
    visual_system_stylesheet,
)

ROOT = Path(__file__).resolve().parents[1]


def test_a81_selects_soft_professional_without_removing_reference_concepts() -> None:
    assert ACTIVE_CONCEPT == "soft_professional"
    assert tuple(CONCEPTS) == ("precision", "soft_professional", "modern_technical")


def test_a81_selected_light_palette_matches_reviewed_soft_professional_contract() -> None:
    p = SOFT_PROFESSIONAL_LIGHT
    assert (p.canvas, p.surface, p.surface_secondary, p.border) == (
        "#F7F6F3",
        "#FFFFFF",
        "#F1F0EC",
        "#E3E0D9",
    )
    assert (p.primary, p.primary_hover, p.primary_soft) == ("#5271C6", "#465FA8", "#ECF0FB")


def test_a81_default_application_overlay_uses_soft_professional_not_modern_technical() -> None:
    selected = visual_system_stylesheet(is_dark=False)
    explicit_soft = visual_system_stylesheet(is_dark=False, concept_key="soft_professional")
    technical = visual_system_stylesheet(is_dark=False, concept_key="modern_technical")
    assert selected == explicit_soft
    assert selected != technical
    assert SOFT_PROFESSIONAL_LIGHT.primary in selected
    assert MODERN_TECHNICAL_LIGHT.primary not in selected


def test_a81_selected_badge_uses_semantic_selected_tokens_instead_of_hard_coded_technical_blue() -> None:
    qss = selected_concept_badge_stylesheet()
    assert SOFT_PROFESSIONAL_LIGHT.primary_soft in qss
    assert SOFT_PROFESSIONAL_LIGHT.primary in qss
    assert MODERN_TECHNICAL_LIGHT.primary_soft not in qss


def test_a81_soft_professional_keeps_a_dark_counterpart_for_existing_theme_compatibility() -> None:
    assert SOFT_PROFESSIONAL_DARK.canvas != SOFT_PROFESSIONAL_LIGHT.canvas
    assert SOFT_PROFESSIONAL_DARK.surface != SOFT_PROFESSIONAL_LIGHT.surface
    assert SOFT_PROFESSIONAL_DARK.primary != SOFT_PROFESSIONAL_LIGHT.primary


def test_a81_reference_specimens_stay_distinct_after_direction_change() -> None:
    previews = {key: concept_preview_stylesheet(key) for key in CONCEPTS}
    assert len(set(previews.values())) == 3


def test_a81_records_a9_as_structural_not_color_only_migration() -> None:
    joined = " | ".join(A9_HANDOFF_PRINCIPLES).lower()
    assert "structural workspace modernization" in joined
    assert "not another color-only skin" in joined
    assert "queue remains the dominant" in joined
    assert "preserve explicit preflight and generation authority" in joined
    assert len(SELECTED_DIRECTION_RATIONALE) >= 3


def test_a81_direction_correction_has_no_generation_or_provider_authority() -> None:
    source = (ROOT / "app/gui/visual_design_system_v2.py").read_text(encoding="utf-8")
    dialog = (ROOT / "app/gui/dialogs/visual_design_system_dialog.py").read_text(encoding="utf-8")
    combined = source + "\n" + dialog
    for forbidden in (
        "generation_controller",
        "run_preflight(",
        "smart_provider_routing_service",
        "setCurrentText(",
        "refresh_catalog(",
    ):
        assert forbidden not in combined
