# Roadmap 2 B6 Hotfix 3 — Hotfix 5

## Scope

This continuation repairs a brittle Hotfix 2 regression assertion after the production/UI fixes through Hotfix 4 already passed their dedicated monitor-layout checks.

The failing assertion searched for the first `yield` in `tests/conftest.py`. That first occurrence belongs to the session-scoped `qt_app` fixture (`yield app`), not the autouse `isolate_qsettings_between_tests` fixture whose teardown order the test intended to validate. Consequently the source-order test compared the font restore against the *pre-test* `settings.clear()` and failed even though the actual fixture restores the QApplication font during teardown before its post-test settings cleanup.

Hotfix 5 changes only the regression test so it scopes its source-order checks to `isolate_qsettings_between_tests` and its own indented `yield` statement. No production source, provider behavior, routing, Preflight, Generation, Smart Routing, credential storage, database schema, theme palette, or runtime geometry contract is changed by this continuation.

## Acceptance

- Hotfix 2 font-isolation regression passes for the correct fixture scope.
- Hotfix 4 persistent active Generation Monitor constraint remains green.
- Hotfix 3 responsive-monitor regression remains green.
- A12 -> A11.1 order regression remains green.
- Hotfix 1/2/3/4 dedicated regressions remain green.
- System / Light / Dark runtime screenshots are generated with readable fonts.
- B6 operations, Track A authority, credential/runtime/portable guards and database schema 23 remain preserved.
- Full Quality Gate runs exactly once and passes before commit/push.
