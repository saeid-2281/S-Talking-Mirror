# S Talking v0.17 Product Polish

This pass turns several v0.16 foundations into visible product workflows while preserving the existing generation engine, providers, migrations, packaging, and tests.

## Completed in this pass

- Source imports now open a review dialog before queue jobs are created.
- Source review shows file/sheet metadata, detected columns, mappings, row counts, rejected rows, status, and collision summary.
- Project Sources dock has compact actions for add, remove, replace, refresh, reorder, open folder, and report.
- Queue filtering now includes source-aware filtering alongside status filtering.
- Provider capability cards expose factual setup state and badges without requiring optional SDKs or secrets at startup.
- Quick Setup is available from Help and writes global defaults only after Finish.
- Main window supports source/project drag and drop, branded empty state, additional shortcuts, and expanded command palette entries.
- Notifications, activity timeline, batch sessions, workspace preferences, and source-level settings have idempotent migration tables.
- Finished generation reports are recorded into notification, activity, and batch-session history tables.

## Completed in v0.17.1 RC2 readiness

- Shared release identity is `0.17.2-rc2` across app metadata, package metadata, and Windows version resources.
- Source workflow services now support missing-source relocation, refresh diffs, enable/disable, stable reordering, and explicit collision strategies.
- Output subfolders are respected when resolving job output paths.
- Preflight validates providers through capability/setup cards and blocks mixed-provider overrides with an actionable message.
- Optional Azure, Google, Amazon Polly, and Kokoro adapters remain startup-safe and synthesize when their official SDK/runtime is installed.
- Build output now includes `installer-result.json` and an Inno Setup script for unsigned installer builds.
- Large-queue controller filtering and sorting are covered by 10,000-job regression tests.

## Deferred Scope

The following v0.17 areas are intentionally not completed in this pass because they require larger provider or model-view work:

- Full SDK-backed Azure, Google Cloud TTS, Amazon Polly, and Kokoro synthesis.
- Live credentialed validation for Azure, Google Cloud TTS, Amazon Polly, and Kokoro runtime installations.
- Full dynamic provider settings schemas for every provider-specific option.
- Complete source refresh diff/apply workflow and collision-renaming strategies.
- QTableView/model-view migration for 10,000-row incremental rendering.
- Mini monitor, full Notification Center, Activity Timeline dialog, Batch History dialog, and Windows installer.
- Full installer compile requires Inno Setup (`ISCC.exe`) on the build machine; without it, the build records an explicit placeholder installer artifact.

These deferred items have persistence and capability foundations where applicable, but should be finished as separate focused slices.
