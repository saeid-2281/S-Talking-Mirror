# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 6 / Hotfix 1

## Inherited H2 Geometry Contract Reconciliation

Hotfix 6 completed the canonical queue-composition repair: its own four tests,
Hotfix 5 fixed-chrome tests, Hotfix 4 structural-disclosure tests and Hotfix 3
responsive-disclosure tests all passed. The run then stopped in the inherited
Hotfix 2 source-level contract because that historical test still required the
literal call `queue.updateGeometry()`.

That assertion is stale after Hotfix 5. The fixed `queueChromeHost` introduced
`queue.sync_chrome_height()` as the stronger and more specific geometry
authority: it locks the chrome host to `root_layout.sizeHint()` so spare window
height belongs to the work surface instead of queue chrome. Hotfix 6 preserves
that contract and all runtime geometry tests already passed before the inherited
source assertion was reached.

This continuation changes no production/runtime source. It updates only the
inherited H2 test contract to require `queue.sync_chrome_height()` after
`root.invalidate()`, then reruns the entire H9 continuation chain before any
Full Quality Gate, commit, push, or Portable build.

Provider/account/voice/model/language authority, Preflight, Generation, Smart
Routing, credential storage, portable data semantics and database schema 23 are
unchanged.
