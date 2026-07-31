# Phase C final quality fix

- Removed the unused `ActivityEvent` runtime import from the activity timeline widget.
- Added `scripts/quality-gate.ps1`.
- Added an opt-in repository pre-commit hook under `.githooks/pre-commit`.
- Run `scripts/install-git-hooks.ps1` once to enable the hook.
- The default hook runs compileall, Ruff, and focused regression tests.
- Run `scripts/quality-gate.ps1 -Full` for the full test suite.
