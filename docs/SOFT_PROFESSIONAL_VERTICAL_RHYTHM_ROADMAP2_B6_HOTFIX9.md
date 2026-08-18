# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 — Vertical Rhythm & Typography Unification

## Reason

Manual acceptance of the real `dd9364dc` portable build found two remaining visual-quality defects that were not represented by the earlier pixel-color gates:

1. the collapsed queue workspace donated too much vertical height to non-working chrome between the launch strip and the queue body; and
2. historical component styles left multiple body/control font sizes and control heights visible in the same main workspace.

The approved A8 **Soft Professional** concept already defines the intended contract: a compact 11/12/13/14/18px type scale, 34px compact controls, calm section spacing, and a queue-dominant working surface. This hotfix makes the real desktop shell follow that contract.

## Presentation changes

- queue heading is a fixed 44px band;
- wide/standard queue command center is a fixed two-row 80px band;
- duplicate inner vertical margins are removed from the command rows;
- queue summary is fixed at 30–32px and the remaining height belongs to the queue body;
- generation and queue controls use one 34px compact height;
- visual hierarchy comes from semantic color/weight rather than arbitrary button height;
- main toolbar, queue, provider/inspector controls and public workspace tabs use the A8 13px body scale;
- captions/helpers use 11px, compact summaries 12px, section headings 14px and project title 18px.

## Authority freeze

This is presentation-only. It does not add or change provider/account/voice/model/language switching, Preflight execution, Generation execution, Smart Routing, cross-provider failover, credential handling, portable runtime routing, project persistence or database schema 23.
