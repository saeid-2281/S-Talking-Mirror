# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 4

## Structural Queue Disclosure Composition

Hotfix 9 H1-H3 established that visibility flags, zero-height constraints and
removing only the Batch range row were insufficient to eliminate the frozen
Windows queue dead slot. H3 evidence was decisive: Workflow and Batch widgets
were hidden and the range widget was absent from the layout, yet the collapsed
heading-to-command gap remained 50px.

H4 makes layout membership the presentation authority. The optional Generation
Workflow, Queue Batch Operations and row-range surfaces are removed from
`QueueWorkspace.root_layout` while collapsed. Explicit disclosure reinserts the
existing widgets immediately before the command host, preserving every historical
controller/service and action path. No new generation, Preflight, provider,
routing, credential or database behavior is introduced.

The historical Phase89/Phase92 integration tests are reconciled with A9
progressive disclosure: the same widget instances and shortcuts remain present,
but their default collapsed state consumes no layout item. Ctrl+Alt+G and
Ctrl+Alt+Q still surface the existing controls on demand, including in compact
workspaces.

Soft Professional H9 typography (11/12/13/14/18), 34px central controls, 46px
queue heading, 44px generation launch band, H8 color certification, Track A
authority and database schema 23 remain unchanged.
