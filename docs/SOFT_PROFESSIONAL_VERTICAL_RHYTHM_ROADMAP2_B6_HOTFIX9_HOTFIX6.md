# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 6

## Canonical Queue Chrome Ordering & Logical Disclosure Authority

Hotfix 5 isolated queue chrome from the expanding work surface and passed four
of five focused tests. The remaining failure was no longer a vertical-growth
problem: an explicitly opened Batch surface appeared at root-layout index 2
instead of index 1.

The cause was composition ambiguity. `_sync_queue_disclosure_layout()` removed
Workflow and Batch before rebuilding, but could leave an already-attached
`range_host` in place. In addition, sibling disclosure state was inferred from
raw QWidget visibility. A transient visible child could therefore be mistaken
for an explicit A9 disclosure request.

Hotfix 6 makes the composition deterministic:

- logical A9 `_workflow_expanded` / `_batch_expanded` state gates physical
  visibility when sibling state is reconstructed;
- Workflow, Batch and Range are all detached before canonical composition;
- explicit Batch order is always `Heading -> Batch -> Range -> Command`;
- explicit Workflow + Batch order is
  `Heading -> Workflow -> Batch -> Range -> Command`;
- collapsed state remains `Heading -> Command`;
- the H5 fixed `queueChromeHost` remains unchanged, so spare desktop height
  continues to belong only to the queue work surface.

This is presentation-only. Provider/account/voice/model/language authority,
Preflight, Generation, Smart Routing, credential storage, portable data
semantics and database schema 23 are unchanged.
