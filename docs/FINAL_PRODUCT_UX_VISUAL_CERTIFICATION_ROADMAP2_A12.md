# Roadmap 2 A12 — Final Product UX & Visual Certification

## Purpose

A12 is the final certification phase for the Roadmap 2 visual/product redesign.
It does **not** introduce another production UI skin or restructure business
workflow.  The certified production baseline is A11.1 + Hotfix 4:

`eec5ade2b2017b17b45248e68c174801bebd353a`

The selected product direction remains **Soft Professional**.

## Certification boundary

A12 certifies the real runtime product across the work completed in A8–A11.1:

- A8/A8.1 visual design system and Soft Professional direction;
- A9/A9.1 main workspace modernization and visual alignment;
- A10 dialogs, forms and data-dense UX;
- A11 Light/Dark/System theme and visual accessibility;
- A11.1 toolbar/icon fidelity, metric-radius stability, Generation Monitor fit,
  Provider Accounts details geometry, Provider overview fit, and dialog-lifetime
  safety.

No provider/account/voice/model/language authority, Preflight authority,
generation authority, Smart Routing authority, hidden failover behavior, source
text, persistence contract, or database schema is changed by A12.

## Machine certification

`scripts/certify_product_ux_visual_roadmap2_a12.py` runs against an isolated
temporary runtime and isolated INI-backed QSettings location.  It does not read
the operator's local credential/profile files.

The certifier verifies:

1. selected visual direction is `soft_professional`;
2. Light and Dark semantic contrast audits pass;
3. A9/A10/A11/A11.1 modernizers are installed;
4. key public visual handles remain present;
5. Light theme resolves consistently through QPalette + A11 semantics;
6. main-toolbar icons use the canonical 20x20 action-icon contract;
7. operational metric cards retain a 12px radius through active/filter state;
8. Provider overview fits the narrow provider dock without horizontal pressure;
9. no detached `Scope & Order` top-level window is introduced;
10. Generation Monitor keeps the historical 290px minimum-width API while its
    active real width is 320–340px;
11. Provider Accounts Center provides a readable details pane and usable actions;
12. Dark theme resolves consistently;
13. System theme remains palette-driven;
14. all required visual evidence is generated and non-empty.

## Runtime evidence

The certification output is written to:

`artifacts/product-ux-visual-certification/roadmap2-a12/`

Evidence:

- `main-light.png`
- `generation-monitor-light.png`
- `provider-accounts-light.png`
- `main-dark.png`
- `certification.json`
- `index.html`

The screenshots are generated from an isolated runtime, so local API profiles and
credentials are not included.

## Final gate

A12 is certified only when all of the following are true:

- dedicated A12 tests pass;
- the runtime certification status is `CERTIFIED`;
- visual/theme/dialog/workspace/Generation Monitor/Provider Accounts/Phase 86/Q2
  regressions pass;
- Track A authority guards remain byte-identical;
- Database schema 23 remains unchanged;
- the Full Quality Gate passes once on the final A12 source;
- the exact A12 certification source is committed and pushed;
- the source working tree is clean excluding the two local-only profile files.

After A12 certification, the Roadmap 2 visual redesign is complete and the next
product-development stage is **B1 — Intelligent TTS Production**.
