"""Roadmap 2 A8 semantic visual system for the S-Talking desktop product.

This module deliberately sits beside the legacy ``design_system`` and ``theme``
modules.  A8 establishes a forward-looking visual contract without breaking the
historic density, theme, accessibility, or widget handles that A9-A12 still
need to migrate incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticPalette:
    canvas: str
    surface: str
    surface_secondary: str
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_inverse: str
    primary: str
    primary_hover: str
    primary_soft: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    info: str
    info_soft: str
    focus_ring: str


@dataclass(frozen=True)
class TypographyScale:
    family: str = '"Segoe UI Variable", "Segoe UI", sans-serif'
    caption: int = 11
    label: int = 12
    body: int = 13
    section: int = 14
    title: int = 18
    display: int = 22
    regular_weight: int = 400
    medium_weight: int = 500
    semibold_weight: int = 600
    bold_weight: int = 700


@dataclass(frozen=True)
class SpacingScale:
    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32


@dataclass(frozen=True)
class RadiusScale:
    control: int
    compact_surface: int
    card: int
    panel: int


@dataclass(frozen=True)
class ElevationScale:
    base_border: int = 1
    raised_border: int = 1
    overlay_border: int = 1
    raised_tone: str = "subtle"
    overlay_tone: str = "strong"


@dataclass(frozen=True)
class IconScale:
    compact: int = 16
    standard: int = 20
    prominent: int = 24
    feature: int = 32
    style: str = "outline"
    stroke_contract: str = "consistent-1.75-to-2px"


@dataclass(frozen=True)
class ComponentMetrics:
    toolbar_height: int
    generation_action_bar_height: int
    control_compact_height: int
    control_comfortable_height: int
    icon_button_height: int
    queue_row_compact_height: int
    queue_row_comfortable_height: int
    card_padding: int
    panel_padding: int
    section_gap: int


@dataclass(frozen=True)
class ConceptSpec:
    key: str
    name: str
    description: str
    characteristics: tuple[str, ...]
    light: SemanticPalette
    dark: SemanticPalette
    radii: RadiusScale
    metrics: ComponentMetrics


@dataclass(frozen=True)
class InventoryItem:
    area: str
    current_surface: str
    a8_contract: str
    migration_phase: str


TYPOGRAPHY = TypographyScale()
SPACING = SpacingScale()
ELEVATION = ElevationScale()
ICONS = IconScale()

# Compatibility-sensitive desktop measurements.  These intentionally preserve
# the long-lived queue/toolbar contracts while A8 changes the visual language.
COMPONENTS = ComponentMetrics(
    toolbar_height=42,
    generation_action_bar_height=44,
    control_compact_height=34,
    control_comfortable_height=38,
    icon_button_height=34,
    queue_row_compact_height=30,
    queue_row_comfortable_height=32,
    card_padding=12,
    panel_padding=12,
    section_gap=8,
)


PRECISION_LIGHT = SemanticPalette(
    canvas="#F4F6F8",
    surface="#FFFFFF",
    surface_secondary="#EEF1F4",
    border="#D8DEE5",
    border_strong="#B9C2CC",
    text_primary="#151A20",
    text_secondary="#4F5B67",
    text_muted="#7E8995",
    text_inverse="#FFFFFF",
    primary="#315FC8",
    primary_hover="#294FA9",
    primary_soft="#E8EFFD",
    success="#19724C",
    success_soft="#E6F4EC",
    warning="#A96813",
    warning_soft="#FFF1DA",
    danger="#B63E43",
    danger_soft="#FBE8E9",
    info="#356EA8",
    info_soft="#E8F1FA",
    focus_ring="#315FC8",
)
PRECISION_DARK = SemanticPalette(
    canvas="#0F1318",
    surface="#151A20",
    surface_secondary="#1B222A",
    border="#2D3640",
    border_strong="#465260",
    text_primary="#F4F6F8",
    text_secondary="#B8C1CB",
    text_muted="#87939F",
    text_inverse="#10141A",
    primary="#7B9EF2",
    primary_hover="#91AFF7",
    primary_soft="#1C2A47",
    success="#65C394",
    success_soft="#173528",
    warning="#E4A650",
    warning_soft="#402F17",
    danger="#EB7B80",
    danger_soft="#431F23",
    info="#74A9DD",
    info_soft="#1B3147",
    focus_ring="#92AFF7",
)

SOFT_PROFESSIONAL_LIGHT = SemanticPalette(
    canvas="#F7F6F3",
    surface="#FFFFFF",
    surface_secondary="#F1F0EC",
    border="#E3E0D9",
    border_strong="#C9C4BA",
    text_primary="#1D201F",
    text_secondary="#626762",
    text_muted="#6C726B",
    text_inverse="#FFFFFF",
    primary="#5271C6",
    primary_hover="#465FA8",
    primary_soft="#ECF0FB",
    success="#2B7655",
    success_soft="#EAF5EF",
    warning="#8F5F1D",
    warning_soft="#FFF3DF",
    danger="#A94646",
    danger_soft="#FBEDED",
    info="#476A91",
    info_soft="#EDF3F8",
    focus_ring="#5271C6",
)
SOFT_PROFESSIONAL_DARK = SemanticPalette(
    canvas="#121413",
    surface="#181B19",
    surface_secondary="#202420",
    border="#313631",
    border_strong="#4A524A",
    text_primary="#F3F4F1",
    text_secondary="#BEC3BC",
    text_muted="#8E958C",
    text_inverse="#121412",
    primary="#89A1E3",
    primary_hover="#9BAFE8",
    primary_soft="#26304A",
    success="#75BE98",
    success_soft="#1C3528",
    warning="#DBA65A",
    warning_soft="#3E301D",
    danger="#DF8585",
    danger_soft="#422425",
    info="#8AAED1",
    info_soft="#223447",
    focus_ring="#9BAFE8",
)

# Modern Technical remains one of the three A8 reference concepts.  A8.1
# changes the active product direction to Soft Professional after visual review;
# the Modern Technical tokens stay available for comparison and future reference.
MODERN_TECHNICAL_LIGHT = SemanticPalette(
    canvas="#F6F7F9",
    surface="#FFFFFF",
    surface_secondary="#F1F3F5",
    border="#E2E5E9",
    border_strong="#C7CDD5",
    text_primary="#171A1F",
    text_secondary="#606772",
    text_muted="#8A929E",
    text_inverse="#FFFFFF",
    primary="#4768E5",
    primary_hover="#3D5BCB",
    primary_soft="#EDF1FF",
    success="#21865A",
    success_soft="#E8F5EE",
    warning="#C47B18",
    warning_soft="#FFF2DE",
    danger="#C84A4A",
    danger_soft="#FCEBEB",
    info="#3E78C5",
    info_soft="#EAF2FB",
    focus_ring="#4768E5",
)
MODERN_TECHNICAL_DARK = SemanticPalette(
    canvas="#101217",
    surface="#16191F",
    surface_secondary="#1D2129",
    border="#2A303A",
    border_strong="#414A58",
    text_primary="#F5F7FA",
    text_secondary="#B8C0CC",
    text_muted="#8D97A5",
    text_inverse="#111318",
    primary="#7691FF",
    primary_hover="#8DA4FF",
    primary_soft="#222E59",
    success="#69C699",
    success_soft="#17372A",
    warning="#E2A34D",
    warning_soft="#413019",
    danger="#EB7C7C",
    danger_soft="#442124",
    info="#77A8E2",
    info_soft="#1D334C",
    focus_ring="#8DA4FF",
)

CONCEPTS: dict[str, ConceptSpec] = {
    "precision": ConceptSpec(
        key="precision",
        name="Precision",
        description="High-clarity operational UI with firmer borders and compact geometry.",
        characteristics=("crisp boundaries", "high scan speed", "operator-first density"),
        light=PRECISION_LIGHT,
        dark=PRECISION_DARK,
        radii=RadiusScale(control=4, compact_surface=5, card=6, panel=7),
        metrics=COMPONENTS,
    ),
    "soft_professional": ConceptSpec(
        key="soft_professional",
        name="Soft Professional",
        description="Calm professional surfaces with warmer neutrals and gentler containers.",
        characteristics=("calm long sessions", "soft grouping", "friendly professional tone"),
        light=SOFT_PROFESSIONAL_LIGHT,
        dark=SOFT_PROFESSIONAL_DARK,
        radii=RadiusScale(control=8, compact_surface=9, card=12, panel=14),
        metrics=COMPONENTS,
    ),
    "modern_technical": ConceptSpec(
        key="modern_technical",
        name="Modern Technical",
        description="Modern desktop SaaS hierarchy tuned for production queues, provider state and launch decisions.",
        characteristics=("neutral technical surfaces", "controlled blue accent", "semantic operational states"),
        light=MODERN_TECHNICAL_LIGHT,
        dark=MODERN_TECHNICAL_DARK,
        radii=RadiusScale(control=6, compact_surface=7, card=9, panel=10),
        metrics=COMPONENTS,
    ),
}

ACTIVE_CONCEPT = "soft_professional"

SELECTED_DIRECTION_RATIONALE: tuple[str, ...] = (
    "warmer neutral surfaces for long production sessions",
    "calmer grouping with less technical visual pressure",
    "professional desktop hierarchy without reducing operational clarity",
)

A9_HANDOFF_PRINCIPLES: tuple[str, ...] = (
    "structural workspace modernization, not another color-only skin",
    "queue remains the dominant production surface",
    "provider and inspector areas use quieter grouped hierarchy",
    "reduce stacked horizontal command bars and repeated border noise",
    "preserve explicit Preflight and generation authority",
)


UI_INVENTORY: tuple[InventoryItem, ...] = (
    InventoryItem("Application shell", "Menu bar, main toolbar, status bar", "global hierarchy + chrome", "A8"),
    InventoryItem("Project context", "ProjectContextBar + source/output context", "quiet context surface", "A8/A9"),
    InventoryItem("Queue metrics", "MetricsStrip / metric pills", "semantic scan hierarchy", "A8/A9"),
    InventoryItem("Provider / Sources", "left workspace dock + provider sections", "surface + field hierarchy", "A8/A9"),
    InventoryItem("Queue command center", "QueueWorkspace + filters + actions", "action hierarchy + density", "A8/A9"),
    InventoryItem("Queue table", "QueueTableView / status delegate", "data-grid states + selection", "A8/A9"),
    InventoryItem("Selected-row inspector", "right inspector tabs", "readable metadata grouping", "A8/A9"),
    InventoryItem("Generation monitor", "journey + live operations", "operational state hierarchy", "A8/A9"),
    InventoryItem("Text Studio / Sources", "preparation and source workspaces", "editor + data surface language", "A8/A9"),
    InventoryItem("Preflight / launch", "Preflight, launch, pronunciation dialogs", "decision/status semantics", "A8/A10"),
    InventoryItem("Operations / reports", "dense dialogs and evidence views", "data-dense component language", "A8/A10"),
    InventoryItem("Theme / accessibility", "Light, Dark, System + interface prefs", "semantic theme contract", "A8/A11"),
)


def concept(key: str = ACTIVE_CONCEPT) -> ConceptSpec:
    """Return a validated visual concept."""

    try:
        return CONCEPTS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown visual concept: {key}") from exc


def palette_for(*, is_dark: bool, concept_key: str = ACTIVE_CONCEPT) -> SemanticPalette:
    spec = concept(concept_key)
    return spec.dark if is_dark else spec.light


def _global_qss(spec: ConceptSpec, palette: SemanticPalette) -> str:
    """Return the A8 overlay applied to existing S-Talking widgets.

    The overlay is intentionally visual-only: it does not set dock widths,
    queue row heights, toolbar height, or workspace geometry.  Those existing
    compatibility contracts remain authoritative until A9/A10 migration.
    """

    r = spec.radii
    t = TYPOGRAPHY
    return f"""
/* Roadmap 2 A8 — Visual Design System 2.0 / {spec.name} */
QDialog {{ background: {palette.canvas}; color: {palette.text_primary}; }}
QMenuBar {{
    background: {palette.surface};
    color: {palette.text_secondary};
    border-bottom: 1px solid {palette.border};
    font-family: {t.family};
    font-size: {t.body}px;
}}
QMenuBar::item {{ padding: 5px 9px; border-radius: {r.control}px; }}
QMenuBar::item:selected {{ background: {palette.surface_secondary}; color: {palette.text_primary}; }}
QMenu {{
    background: {palette.surface};
    color: {palette.text_primary};
    border: 1px solid {palette.border_strong};
    border-radius: {r.card}px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 24px 6px 9px; border-radius: {r.control}px; }}
QMenu::item:selected {{ background: {palette.primary_soft}; color: {palette.text_primary}; }}
QToolBar#mainToolbar {{
    background: {palette.surface};
    border: 0;
    border-bottom: 1px solid {palette.border};
    spacing: 2px;
}}
QToolBar#mainToolbar QToolButton {{
    color: {palette.text_secondary};
    background: transparent;
    border: 1px solid transparent;
    border-radius: {r.control}px;
    padding: 5px 8px;
}}
QToolBar#mainToolbar QToolButton:hover {{ background: {palette.surface_secondary}; color: {palette.text_primary}; }}
QToolBar#mainToolbar QToolButton:pressed {{ background: {palette.primary_soft}; color: {palette.primary}; }}
QLabel#projectContextBar, QFrame#projectContextBar {{
    background: {palette.surface};
    color: {palette.text_secondary};
    border: 1px solid {palette.border};
    border-radius: {r.compact_surface}px;
    padding: 5px 9px;
}}
QFrame#metricsStrip {{ background: transparent; border: 0; }}
QFrame#metricPill, QFrame#metricCard, QFrame#card {{
    background: {palette.surface};
    border: 1px solid {palette.border};
    border-radius: {r.card}px;
}}
QFrame#metricPill:hover {{ border-color: {palette.border_strong}; background: {palette.surface_secondary}; }}
QLabel#metricValue, QLabel#cardValue {{ color: {palette.text_primary}; font-weight: 600; }}
QLabel#metricCaption, QLabel#cardCaption {{ color: {palette.text_muted}; }}
QDockWidget {{ color: {palette.text_secondary}; font-weight: 600; }}
QDockWidget::title {{
    background: {palette.surface_secondary};
    border: 1px solid {palette.border};
    padding: 6px 8px;
}}
QTabWidget::pane {{ border: 1px solid {palette.border}; background: {palette.surface}; }}
QTabBar::tab {{
    background: {palette.surface_secondary};
    color: {palette.text_secondary};
    border: 1px solid {palette.border};
    padding: 6px 10px;
}}
QTabBar::tab:selected {{ background: {palette.surface}; color: {palette.primary}; border-bottom-color: {palette.primary}; }}
QFrame#providerPanel, QWidget#sourcesWorkspacePanel, QFrame#sourcesWorkspaceHeader,
QFrame#sourcesActionBar, QWidget#queueWorkspace, QFrame#selectedRowCard {{
    background: {palette.surface};
    color: {palette.text_primary};
}}
QFrame#providerSection, QFrame#collapsibleSection {{
    background: {palette.surface};
    border: 1px solid {palette.border};
    border-radius: {r.card}px;
}}
QToolButton#providerSectionHeader, QToolButton#sectionHeader {{
    background: transparent;
    color: {palette.text_primary};
    border: 0;
    border-radius: {r.control}px;
    font-weight: 600;
    text-align: left;
}}
QToolButton#providerSectionHeader:hover, QToolButton#sectionHeader:hover {{ background: {palette.surface_secondary}; }}
QLabel#sourcesWorkspaceTitle, QLabel#previewTitle {{ color: {palette.text_primary}; font-weight: 600; }}
QLabel#sourcesWorkspaceSubtitle, QLabel#sourcesWorkspaceHelper {{ color: {palette.text_secondary}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {palette.surface};
    color: {palette.text_primary};
    border: 1px solid {palette.border_strong};
    border-radius: {r.control}px;
    selection-background-color: {palette.primary};
    selection-color: {palette.text_inverse};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {palette.focus_ring}; }}
QPushButton {{
    background: {palette.surface};
    color: {palette.text_primary};
    border: 1px solid {palette.border_strong};
    border-radius: {r.control}px;
}}
QPushButton:hover {{ background: {palette.surface_secondary}; border-color: {palette.border_strong}; }}
QPushButton:pressed {{ background: {palette.primary_soft}; }}
QPushButton[primary="true"], QPushButton#startGenerationButton {{
    background: {palette.primary};
    color: {palette.text_inverse};
    border-color: {palette.primary};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover, QPushButton#startGenerationButton:hover {{ background: {palette.primary_hover}; }}
QTableView, QTableWidget {{
    background: {palette.surface};
    alternate-background-color: {palette.surface_secondary};
    color: {palette.text_primary};
    gridline-color: {palette.border};
    border: 1px solid {palette.border};
    selection-background-color: {palette.primary_soft};
    selection-color: {palette.text_primary};
}}
QHeaderView::section {{
    background: {palette.surface_secondary};
    color: {palette.text_secondary};
    border: 0;
    border-right: 1px solid {palette.border};
    border-bottom: 1px solid {palette.border_strong};
    padding: 6px 8px;
    font-weight: 600;
}}
QProgressBar {{
    background: {palette.surface_secondary};
    border: 1px solid {palette.border};
    border-radius: {r.control}px;
    color: {palette.text_secondary};
}}
QProgressBar::chunk {{ background: {palette.primary}; border-radius: {r.control}px; }}
QLabel[status="success"], QLabel[state="completed"] {{ color: {palette.success}; }}
QLabel[status="warning"], QLabel[state="running"] {{ color: {palette.warning}; }}
QLabel[status="danger"], QLabel[state="failed"] {{ color: {palette.danger}; }}
QLabel[status="info"] {{ color: {palette.info}; }}
QStatusBar {{ background: {palette.surface}; color: {palette.text_muted}; border-top: 1px solid {palette.border}; }}
""".strip()


def visual_system_stylesheet(*, is_dark: bool, concept_key: str = ACTIVE_CONCEPT) -> str:
    """Build the application-level A8 visual overlay."""

    spec = concept(concept_key)
    return _global_qss(spec, palette_for(is_dark=is_dark, concept_key=concept_key))


def concept_preview_stylesheet(concept_key: str) -> str:
    """Scoped specimen styling used by the A8 comparison dialog."""

    spec = concept(concept_key)
    p = spec.light
    r = spec.radii
    return f"""
QFrame#conceptSpecimen {{ background:{p.canvas}; border:1px solid {p.border}; border-radius:{r.panel}px; }}
QFrame#specimenToolbar, QFrame#specimenProvider, QFrame#specimenQueue {{ background:{p.surface}; border:1px solid {p.border}; border-radius:{r.card}px; }}
QLabel#specimenTitle {{ color:{p.text_primary}; font-size:{TYPOGRAPHY.section}px; font-weight:700; }}
QLabel#specimenSecondary {{ color:{p.text_secondary}; }}
QLabel#specimenMuted {{ color:{p.text_muted}; }}
QPushButton {{ background:{p.surface}; color:{p.text_primary}; border:1px solid {p.border_strong}; border-radius:{r.control}px; padding:5px 9px; }}
QPushButton#specimenPrimary {{ background:{p.primary}; color:{p.text_inverse}; border-color:{p.primary}; font-weight:600; }}
QLabel#specimenSuccess {{ color:{p.success}; background:{p.success_soft}; border-radius:{r.control}px; padding:3px 6px; }}
QLabel#specimenWarning {{ color:{p.warning}; background:{p.warning_soft}; border-radius:{r.control}px; padding:3px 6px; }}
QLabel#specimenDanger {{ color:{p.danger}; background:{p.danger_soft}; border-radius:{r.control}px; padding:3px 6px; }}
QTableWidget {{ background:{p.surface}; alternate-background-color:{p.surface_secondary}; color:{p.text_primary}; border:1px solid {p.border}; gridline-color:{p.border}; }}
QHeaderView::section {{ background:{p.surface_secondary}; color:{p.text_secondary}; border:0; border-bottom:1px solid {p.border_strong}; padding:5px; font-weight:600; }}
""".strip()


def selected_concept_badge_stylesheet(concept_key: str = ACTIVE_CONCEPT) -> str:
    """Style the selected-direction badge from semantic tokens, never hard-coded concept colors."""

    spec = concept(concept_key)
    p = spec.light
    r = spec.radii
    return (
        f"padding:8px 10px;border-radius:{r.control}px;font-weight:600;"
        f"background:{p.primary_soft};color:{p.primary};border:1px solid {p.border_strong};"
    )


def token_rows(concept_key: str = ACTIVE_CONCEPT) -> tuple[tuple[str, str], ...]:
    """Flatten the selected light token set for readable UI/docs/tests."""

    spec = concept(concept_key)
    p = spec.light
    return (
        ("Canvas", p.canvas),
        ("Surface", p.surface),
        ("Surface secondary", p.surface_secondary),
        ("Border", p.border),
        ("Text primary", p.text_primary),
        ("Text secondary", p.text_secondary),
        ("Text muted", p.text_muted),
        ("Primary", p.primary),
        ("Primary hover", p.primary_hover),
        ("Success", p.success),
        ("Warning", p.warning),
        ("Danger", p.danger),
        ("Info", p.info),
    )
