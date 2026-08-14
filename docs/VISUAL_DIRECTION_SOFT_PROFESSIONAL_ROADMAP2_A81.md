# Roadmap 2 A8.1 — Soft Professional Direction Correction

## Purpose

A8 established three real S-Talking visual concepts: Precision, Soft Professional, and Modern Technical. After reviewing the concepts beside the actual running application, A8.1 changes the official product direction from **Modern Technical** to **Soft Professional** before structural workspace modernization begins.

This is a visual-direction correction, not a feature phase and not a layout migration. A9 remains responsible for restructuring the Main Workspace.

## Selected direction

**Soft Professional** is now the active visual concept. The selected light semantic palette is:

- Canvas `#F7F6F3`
- Surface `#FFFFFF`
- Surface secondary `#F1F0EC`
- Border `#E3E0D9`
- Border strong `#C9C4BA`
- Text primary `#1D201F`
- Text secondary `#626762`
- Text muted `#90958F`
- Primary `#5271C6`
- Primary hover `#465FA8`
- Primary soft `#ECF0FB`
- Success `#2E7D5A`
- Warning `#B27825`
- Danger `#BD5353`
- Info `#557DAA`

The other two concepts remain available in the in-app Visual Design System 2.0 reference workspace. No concept is deleted.

## Why the correction is made before A9

The actual A8 screenshot confirmed that changing semantic tokens alone does not make the legacy workspace match the intended concept. The current shell still has excessive stacked command rows, repeated borders, a dense Provider sidebar, compressed inspector/monitor hierarchy, and an undersized empty-state focus area.

A8.1 therefore freezes the correct visual language first, so A9 can perform a real structural modernization rather than optimize the wrong visual direction.

## A9 handoff

A9 must:

1. Modernize structure, not merely apply another stylesheet.
2. Keep the generation queue as the dominant production surface.
3. Reduce stacked horizontal command bars and repeated border noise.
4. Make Provider and Inspector/Monitor regions quieter and more legible.
5. Use whitespace, grouping, typography, and surface hierarchy before adding decoration.
6. Preserve explicit Preflight/generation authority and all Track A invariants.
7. Preserve existing public widget handles unless a tested compatibility adapter is supplied.

## Compatibility boundary

- Track A remains frozen.
- Database schema remains 23.
- No provider/account/voice/model/language automatic switching is introduced.
- No automatic Preflight, generation, or Smart Routing apply is introduced.
- No hidden cross-provider failover is introduced.
- ThemeManager retains root `QPalette` authority.
- A11 still owns final dark-mode and visual-accessibility certification.
