# Roadmap 2 / Q2 — Test Runtime Optimization

## Baseline

Official Q1.1 baseline commit:

`8c219ee619a77b8126c8ddc34177dfd7d7bb9acd`

Stable serial profiled Full Gate:

- 1563 tests
- 1562 passed
- 1 skipped
- 0 failures
- 0 errors
- 2262.104 seconds

Q2 does not increase pytest worker count. It targets the measured wait/repolish cost.

## Optimization 1 — QApplication theme authority

The shared pytest QApplication already owns the active global stylesheet.

Previously every MainWindow also installed the same full stylesheet on itself and
`apply_interface_preferences()` immediately installed it a second time. With more than
80 MainWindow constructions in the suite, Qt repeatedly reparsed and repolished a very
large widget tree.

Q2 keeps QApplication as the theme authority:

- application palette/stylesheet are changed only when the theme actually changes;
- a new MainWindow does not duplicate the application stylesheet;
- icon recoloring runs only on a real theme transition;
- unchanged constructor-time interface preferences do not trigger a second stylesheet pass;
- explicit live preference changes still force a window repolish.

## Optimization 2 — Test-only startup fast path

Pytest sets:

`S_TALKING_TEST_FAST_PATH=1`

This flag is never set by production startup.

Under the test-only path:

- SQLite keeps foreign keys and transactions but uses `synchronous=OFF` and
  `temp_store=MEMORY` for disposable test databases;
- service-container construction skips the automatic generation-maintenance startup
  quick-check; dedicated maintenance tests can still invoke it directly;
- MainWindow still builds its complete UI, loads settings and restores layout state,
  but does not start autosave/performance timers or background startup/recovery/update
  callbacks.

Production behavior remains unchanged when the flag is absent.

## Quality policy

The official gate remains serial-profiled. The Q1 experimental hybrid runner remains
opt-in only.

Q2 performance acceptance for commit:

- Full Quality Gate must pass;
- at least 1500 tests must execute;
- zero failures/errors;
- elapsed time must be <= 1922.788 seconds, which is at least 15% faster
  than the Q1.1 baseline.

If the timing target is missed, automation stops before commit/push and retains the
performance evidence for the next Q2 continuation.

## Architectural invariants

Q2 does not alter:

- provider/engine selection authority;
- Smart Routing recommendation-only behavior;
- Preflight authority;
- Generation Engine authority;
- hidden cross-provider failover policy;
- database schema contract 23.
