# Roadmap 2 A9.1 — Soft Professional Visual Alignment

## Purpose

A9 established the structural main-workspace hierarchy. A real Light-theme product screenshot then showed that the hierarchy was improved, but the visual result still read as a dense Qt/Windows utility rather than the selected A8.1 Soft Professional concept.

A9.1 is therefore a presentation-only alignment pass. It does not change provider selection, source text, language authority, Preflight authority, generation authority, Smart Routing authority, failover behavior, or database schema.

## Screenshot findings addressed

- toolbar and menu chrome were visually legacy and underscaled;
- secondary queue actions used too much filled blue emphasis;
- command/range bars carried too much border noise;
- provider fields and section cards were cramped;
- dock tabs and inspector hierarchy were visually weak;
- the empty state rendered as several large tinted blocks instead of one calm card;
- typography and control sizing did not communicate the 13px-body Soft Professional contract strongly enough;
- central whitespace felt unstructured because the queue shell and empty state did not read as one composed surface.

## A9.1 implementation

- preserves the exact A8.1 Soft Professional semantic palette;
- reserves filled primary emphasis for launch-level actions;
- renders queue Dry run / secondary controls with softer semantic emphasis;
- aligns application typography to Segoe UI Variable / 13px body;
- improves toolbar, menu, tab and input spacing within existing compatibility heights;
- turns queue command/range surfaces into quieter secondary surfaces;
- aligns provider sections, fields and inspector surfaces with 12px card radii;
- removes inherited tinted label blocks inside the empty-state card;
- caps the empty-state height while preserving the A9 maximum-width contract;
- applies real layout spacing/margins to the existing ApplicationShell, QueueWorkspace, launch strip, Provider panel and Selected Row panel;
- preserves A9 responsive behavior: full operator actions in Wide, progressive disclosure + More in Standard/Compact;
- does not target QMainWindow, so ThemeManager remains root QPalette authority.

## Compatibility boundaries

- toolbar maximum height remains governed by the historical <=42px contract;
- generation action-bar height remains governed by the <=44px contract;
- queue row-height contracts remain unchanged;
- Provider dock remains within 270–300px;
- A9 public handles/actions remain intact;
- Track A remains frozen;
- database schema remains 23.

## Exit criterion

A9.1 is complete only after dedicated visual-alignment tests, A9 regressions, historical workspace/theme regressions, Track A authority regressions, DevCheckRunner QProcess regression and one Full Quality Gate pass. A real Light-theme screenshot is reviewed again before A10.

## Hotfix 3 — post-certification screenshot defect repair

The Light-theme review after successful A9.1 certification exposed two presentation defects that automated behavior tests had not made visually obvious:

- the legacy `Scope & order` section label could become a detached top-level Qt window in Wide mode;
- the queue heading and command-center surfaces could consume excessive vertical space, stretching the queue-focus badge and weakening the intended Soft Professional hierarchy.

Hotfix 3 keeps all queue actions and responsive authority unchanged. It permanently suppresses the redundant planning section label, reparents it defensively if Qt has detached it, caps the queue heading/command/range surface heights, constrains the focus badge, and explicitly removes inherited label fills from the queue heading/section labels.

The historical Wide contract remains unchanged: the full operator action set returns in Wide mode, while Standard/Compact continue to use progressive disclosure.
