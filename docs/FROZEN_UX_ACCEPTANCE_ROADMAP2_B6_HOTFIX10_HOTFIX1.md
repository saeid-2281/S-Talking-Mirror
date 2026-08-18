# Roadmap 2 / B6 Hotfix 3 / Hotfix 10 / Hotfix 1

## Scope

This continuation repairs only the static-analysis defects exposed immediately after the Hotfix 10 payload was applied.

Hotfix 10 itself remains unchanged in intent and runtime behavior:

- 42 px main-toolbar host, 24 px icons, 32 px centered toolbar action boxes;
- compact 34 px generation action row with visible `Start` and accessible name `Start generation`;
- visible current-displayed queue row numbers separate from `Source row`;
- direct `Range` disclosure supporting `Original source row` and `Current displayed order` with `From` / `To` controls.

## Repair

1. Escape the three new toolbar QSS blocks inside the existing Python f-string so their braces are emitted as QSS braces instead of being interpreted as Python replacement fields. This resolves Ruff `F821` reports for `padding` / `height` without changing the rendered stylesheet text.
2. Remove the unused `MainWorkspaceModernizer` import from the dedicated Hotfix 10 regression test. This resolves Ruff `F401` without changing test coverage.

No provider, routing, Preflight, Generation, credential, portable-data, database, or Track A authority is changed.

## Acceptance

The continuation must start from the exact failed/uncommitted Hotfix 10 state on certified H9 commit `5d3b448a02c2497997bb0b93a9d8c440fe0c21e2`, pass compile/Ruff, all Hotfix 10 focused regressions, H9/H8 visual certification, the full quality gate, then commit/push the combined Hotfix 10 + Hotfix 1 scope and build one fresh TRUE Portable for manual Frozen UX review.
