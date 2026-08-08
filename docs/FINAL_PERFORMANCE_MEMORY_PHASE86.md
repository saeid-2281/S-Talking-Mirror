# Phase 86 — Final Performance & Memory Optimization

Phase 86 is a behavior-preserving performance pass over the stable S-Talking 1.x runtime. It does not change generation semantics, provider routing, billing, persistence, evidence schemas, release decisions, queue identity, or user data.

## 1. Report dialog lifecycle

`MainWindow._show_report_dialog()` now applies `Qt.WA_DeleteOnClose` centrally. Closing a report or operational dialog therefore releases the underlying Qt object instead of leaving a hidden parent-owned widget alive until the main window exits. The existing runtime-health registry and `report_dialogs` tracker remain authoritative while the dialog is open.

## 2. Lightweight background performance sampling

Periodic sampling now uses `PerformanceStabilityService.collect_background_sample()` with the label `background-light`. It retains the counters needed for long-run RSS/thread/handle growth while avoiding the expensive full `gc.get_objects()` and `QApplication.allWidgets()` enumerations on every timer tick.

Manual samples, snapshots, exports, and managed observations still collect full diagnostics, so release gates and explicit troubleshooting retain the detailed Qt-widget and GC-object evidence.

Custom metric providers remain backward-compatible and continue to supply their complete metric payload.

## 3. Queue render hot-path cleanup

The legacy QTableWidget fallback remains supported, but each render now performs one settings resolution per queue render instead of resolving application settings once per visible row. Output directory, provider, voice, model, and source defaults are also resolved once and reused across the render.

Queue scope statistics are no longer recalculated twice during the same render/progress refresh. Selection-specific text reuses the already-computed visible queue summary.

The existing model/view queue path, feature flag, selection semantics, output-path rules, and generation ordering are unchanged.

## 4. Operations Workspace refresh churn

The consolidated Operations Workspace keeps a compact signature of the domain rows currently rendered. A refresh with identical domain evidence updates the high-level snapshot state but does not destroy and recreate the same QTableWidgetItems and Open buttons. Tool status labels are repolished only when their projected status actually changes.

## Safety and compatibility

- behavior-preserving runtime optimization only
- no automatic GC collection
- no generation/provider/billing/recovery mutation
- no persistence or schema changes
- no evidence format changes
- no queue identity/order changes
- local profile files remain untouched
