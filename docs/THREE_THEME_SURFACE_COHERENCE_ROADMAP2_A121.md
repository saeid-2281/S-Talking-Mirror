# Roadmap 2 A12.1 — Three-Theme Surface Coherence

Official baseline: `babacdadda12663ac5d3d5bbcfe8514fcb65a8ee`

S-Talking exposes exactly three themes: **System**, **Light**, and **Dark**.

The post-A12 runtime screenshot revealed a mixed-surface defect: the modern
Soft Professional canvas/surface family was active in the main workspace while
legacy blue/navy surfaces could remain visible in dock/scroll-area regions.

A12.1 is a presentation-only correction. It appends a final semantic surface
coherence layer through the existing A11 accessibility stylesheet, which is
already the last application stylesheet layer.

For all three themes:

- application shell and dock roots use the semantic `canvas`;
- Provider and Generation Monitor scroll viewports use the same `canvas`;
- Provider sections, Selected Row, and Generation Monitor cards use semantic
  `surface`;
- ThemeManager remains the QApplication/QPalette authority;
- System remains palette-driven;
- no provider/account/voice/model/language, Preflight, Generation, Smart Routing,
  source-text, or database authority changes are introduced.

Evidence is generated in
`artifacts/theme-surface-coherence/roadmap2-a12.1/` as:

- `theme-system.png`
- `theme-light.png`
- `theme-dark.png`
- `certification.json`

A12.1 closes only after dedicated tests, three-theme evidence, focused visual
regressions, Phase 86/Q2 compatibility, Track A authority guards, one Full
Quality Gate, commit/push verification, and a clean source Working Tree.

Next after success: **Roadmap 2 B1 — Intelligent TTS Production**.

## Hotfix 3 — Public theme menu contract

Runtime evidence from Hotfix 2 confirmed that `Graphite` still exists inside
`ThemeManager` and was also being added to `View → Theme` because the menu
blindly iterated every compatibility theme.

The product-facing theme selector is now intentionally limited to:

- System
- Light
- Dark

`Graphite` is **not deleted** from `ThemeManager`. Historical accessibility /
certification code can still request it programmatically, preserving compatibility,
but it is no longer exposed as a fourth end-user theme choice.

This is a presentation-only Main Window menu correction. Provider/account/voice/
model/language selection, Preflight, Generation, Smart Routing, source-text and
database authority are unchanged.
