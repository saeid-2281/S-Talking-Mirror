# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 2

## Structural removal of the collapsed Batch range slot

The first Hotfix 9 continuation proved that a hidden `queueRangeBar` with fixed
zero min/max height could still retain an approximately 50 px slot in the live
Windows `QVBoxLayout` after repeated Qt polish/event passes.

Hotfix 2 changes the presentation contract from advisory geometry to structural
layout membership:

- when Batch plan is closed, `queueRangeBar` is removed from the queue root
  layout and hidden;
- when Batch plan is explicitly opened in Standard/Wide mode, the same existing
  frame is reinserted immediately before `queueCommandBar` as one 42 px row;
- Compact mode always removes the optional row from the layout;
- returning to Wide restores the row only if Batch plan remains explicitly open;
- the queue heading remains 46 px for historical A9.1 compatibility;
- central controls remain 34 px and the A8 Soft Professional typography scale is
  unchanged;
- provider/account/voice/model/language authority, Preflight, Generation, Smart
  Routing, credentials, portable routing and database schema 23 are unchanged.

The H9 certifier now records and requires the collapsed range layout index to be
`-1` and explicitly checks the rendered heading-to-command gap on System, Light
and Dark screenshots.
