# Roadmap 2 B6 Hotfix 2 — Dark Theme Completion

## Purpose

Complete the Soft Professional Dark Theme before the Track B B7 freeze. Real B5 runtime evidence still showed two unrelated dark surface families: the intended warm/neutral semantic surfaces and broad legacy blue/navy slabs in Provider, Inspector, queue, and monitor regions.

## Scope

This hotfix is presentation-only. It adds a final dark-only semantic overlay after the existing A11/A12.1/B2/B4 theme layers. The overlay explicitly maps structural workspace hosts, selected tabs/items, connection state, queue surfaces, inspector cards, monitor cards, and editor controls to the active Soft Professional semantic palette.

Small semantic action/status accents remain palette-driven. The hotfix does not change provider/account/voice/model/language selection, generation, retry, recovery, Preflight, Smart Routing, source text, output integrity, B6 operations intelligence, or database schema 23.

## Visual acceptance

- System / Light / Dark remain public themes.
- Light and System behavior is not replaced by the dark-only completion layer.
- Dark workspace canvas and raised surfaces use one Soft Professional hierarchy.
- Broad legacy navy surface literals are not used by the completion layer.
- Selected tabs/items use neutral semantic surfaces instead of blue-tinted surface fills.
- Primary/action/status colors remain semantic accents rather than becoming structural backgrounds.
- Runtime screenshot evidence is written during certification for manual review before B7.
