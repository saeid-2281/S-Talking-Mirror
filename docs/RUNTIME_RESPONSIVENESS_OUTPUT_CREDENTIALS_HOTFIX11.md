# Roadmap 2 / B6 Hotfix 3 / Hotfix 11

## Frozen runtime responsiveness, Output workspace and local-state migration

This hotfix is a manual-acceptance repair before B7 freeze.

### Runtime responsiveness

The legacy queue table previously rebuilt every visible row on every generation progress signal. A large queue therefore made the Qt GUI spend significant time recreating thousands of `QTableWidgetItem` objects even though only one job changed.

Hotfix 11 keeps the existing full-render path for status-filtered/status-sorted views, but uses a single-row update in the normal **All / CSV-order** production view. Provider execution remains on the existing GenerationController worker/QThread boundary. Provider, voice, model, language, Preflight, Generation and Smart Routing authority are unchanged.

### Output workspace

The Output tab now owns an internal vertical `QScrollArea`, a minimum content height and zero-width-safe file-path geometry. The Activity Center gives Output a larger preferred expanded height. This prevents the Player, File details, Batch review and Output activity controls from being compressed into each other on the Frozen desktop layout while preserving the historical ActivityCenter tab contract.

### Provider account migration

Portable runtime settings live below `S-Talking-Data/settings`. The migration runner merges source `api-profiles.json` by stable `profile_id` and copies only DPAPI-protected `.cred` files into the portable credential directory. It never prints credential contents. The migration runner attempts an immediate DPAPI-to-Windows-Credential-Manager transfer using the existing source environment without printing raw keys; readable legacy DPAPI files remain available as a first-read fallback.

### Local engine migration

A separate runner copies the already-installed `local-engines` and `offline-voices` trees from the prior Portable build, rebases the Local Engines launcher, and rebases the copied portable `settings.json`. No engine download/reinstall is required.

### Acceptance boundary

Before B7 freeze, manually confirm on the freshly built Portable:

- the GUI remains interactive while a Piper request runs against a large queue;
- a one-row Piper generation completes and the correct queue row updates;
- Output playback has no overlapping controls and scrolls when height is constrained;
- migrated provider profiles appear after restart and saved credentials resolve on the same Windows account/machine;
- Piper voice remains available after local-engine migration;
- no automatic provider/account/voice/model/language change is introduced.


## Runner Hotfix 8 — full-suite compatibility reconciliation

Hotfix 8 preserves the H11 incremental legacy-table optimization while restoring later queue contracts that the first H11 structural replacement had overwritten: QueueTableView/model-view rendering, A6 batch-lens snapshot semantics, generation-scope-neutral lens messaging, and A9 progressive-disclosure focus/reveal behavior. The focused compatibility lane now runs these historical contracts before the single Full Quality Gate.
