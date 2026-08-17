# Roadmap 2 B6 Hotfix 3 — Hotfix 4

## Persistent Generation Monitor layout constraint

Hotfix 3 Hotfix 3 proved that recognizing the A11.1 requested width inside the
responsive coordinator was not sufficient. `QMainWindow` can perform another
dock-layout reconciliation *after* the responsive callback returns. Because the
previous repair restored the underlying Qt minimum width to 290 px immediately,
that later native relayout could still collapse the active Generation Monitor to
290 px.

This continuation keeps the active Generation Monitor's **internal Qt min/max
constraint** pinned to its requested presentation width for as long as that tab
owns the shared right dock. `MonitorDockWidget.minimumWidth()` remains the
historical 290 px compatibility API, so established callers and regression
contracts are unchanged. When the user leaves Generation Monitor, the internal
constraint is explicitly released and the generic responsive inspector widths
may take authority again.

## Scope

- presentation/layout only;
- no provider/account/voice/model/language selection changes;
- no Preflight, Generation, Smart Routing, retry, recovery, billing or output
  authority changes;
- credential/runtime/portable contracts remain frozen;
- database schema 23 remains unchanged;
- System / Light / Dark certification remains mandatory before commit.

## Acceptance

1. Active Generation Monitor reports the historical 290 px public minimum.
2. Its internal Qt minimum remains at least 320 px while the A11.1 presentation
   request is active.
3. Forced/repeated responsive refreshes cannot collapse the dock.
4. Leaving Generation Monitor releases the internal presentation lock.
5. The previously failing Hotfix 3 test and A12 -> A11.1 order regression pass.
6. All prior Hotfix 3 focused gates and the Full Quality Gate pass before
   commit/push.
