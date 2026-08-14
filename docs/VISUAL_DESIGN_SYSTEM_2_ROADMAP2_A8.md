# Roadmap 2 A8 — Visual Design System 2.0

## Status and scope

A8 starts the fixed A8–A12 visual/product redesign immediately after the certified Track A freeze. It is a visual-system phase, not a TTS feature phase. Provider, account, voice, model, language, Preflight, generation, routing, pronunciation and persistence authority are unchanged.

A8 does four concrete things:

1. inventories the actual S-Talking desktop surfaces;
2. implements three real visual concepts against S-Talking production vocabulary and components;
3. selects **Modern Technical** as the product direction;
4. formalizes semantic color, typography, spacing, radius, elevation, icon and component metrics for A9–A12.

## Actual UI inventory

The in-app `Visual Design System 2.0` reference covers the real application shell, project context, queue metrics, Provider/Sources dock, Queue Command Center, Queue table, selected-row inspector, Generation Monitor, Text Studio/Sources, Preflight/Launch/Pronunciation, operations/reports, and theme/accessibility surfaces.

A8 applies the selected visual language to existing object names without restructuring workspace geometry. A9 owns main-workspace composition. A10 owns dialogs/forms/data-dense migration. A11 owns independent light/dark visual accessibility certification. A12 owns the final page-by-page visual audit and legacy elimination.

## Three concepts

### Precision

Crisp operational boundaries, compact geometry and high scan speed. Best for a control-room feel, but visually firmer than desired for long desktop sessions.

### Soft Professional

Warmer neutrals, larger radii and calmer grouping. Comfortable and approachable, but slightly less technical for dense provider/queue operations.

### Modern Technical — selected

Neutral cool surfaces, one controlled blue accent, restrained radii and strongly semantic operational states. It best matches the intended product identity:

**Professional AI Production Tool + Modern Desktop SaaS**.

The reference dialog renders all three directions with real S-Talking specimens: New/Sources/Preflight/Start actions, Provider/Voice/Language context, queue rows, explicit language override context, and Ready/Needs review/Blocked status semantics.

## Selected light semantic tokens

| Token | Value |
|---|---|
| Canvas | `#F6F7F9` |
| Surface | `#FFFFFF` |
| Surface Secondary | `#F1F3F5` |
| Border | `#E2E5E9` |
| Text Primary | `#171A1F` |
| Text Secondary | `#606772` |
| Text Muted | `#8A929E` |
| Primary | `#4768E5` |
| Primary Hover | `#3D5BCB` |
| Success | `#21865A` |
| Warning | `#C47B18` |
| Danger | `#C84A4A` |
| Info | `#3E78C5` |

The system also defines paired soft semantic surfaces and a complete dark counterpart. A11 will perform the final dark-mode/contrast pass; A8 establishes the semantic source of truth now.

## Typography, spacing, icons and geometry

- Typography: Segoe UI Variable / Segoe UI fallback; 11 caption, 12 label, 13 body, 14 section, 18 title and 22 display.
- Spacing: 2 / 4 / 8 / 12 / 16 / 24 / 32 px scale.
- Modern Technical radii: 6 control, 7 compact surface, 9 card, 10 panel.
- Icons: outline contract with 16 / 20 / 24 / 32 px sizes and consistent stroke treatment.
- Toolbar contract remains <= 42 px.
- Generation action bar remains <= 44 px.
- Queue rows remain 30 px compact / 32 px comfortable for compatibility.
- Existing monitor width, responsive layout and public widget handles remain authoritative.

## Compatibility strategy

`app/gui/visual_design_system_v2.py` is intentionally additive. It does not replace the historic `app/gui/design_system.py` density helpers and it does not rewrite the legacy `app/gui/theme.py` token contracts. MainWindow appends the A8 semantic overlay to the existing ThemeManager stylesheet and derives light/dark mode from the actual Qt palette, so `System` theme remains system-driven.

This preserves historical contracts such as the legacy theme token values and lets A9–A12 migrate components incrementally instead of forcing a risky one-shot rewrite.

## Authority freeze preserved

A8 does not introduce source text mutation, content-based language detection authority, automatic provider/account/voice/model/language changes, automatic Preflight, automatic generation, automatic Smart Routing apply, or hidden cross-provider failover. Per-job explicit language overrides and user-selected target language remain authoritative. Database schema 23 remains unchanged.

## Next

**Roadmap 2 A9 — Main Workspace Modernization** applies Modern Technical systematically to Main Window navigation, Queue, Provider, Text Studio, Preflight and Generation Monitor hierarchy using the A8 contract.
