# Release Checklist

## Identity

- Version is `0.17.2-rc2`.
- Release channel is `rc`.
- Runtime information, diagnostics, reports, Health Center, and `pyproject.toml` use the shared version.

## Checks

- Run `.\scripts\release-check.ps1`.
- Confirm compileall, pytest, Ruff, database smoke, CSV smoke, preflight smoke, report smoke, diagnostics redaction smoke, and import smoke pass.

## Manual Verification

- Launch with no project.
- Launch with last project restore.
- Open the production project with `input.repaired.csv`.
- Confirm 4,212 valid rows and 0 rejected rows.
- Run Mock preflight and a short generation.
- Test stop/resume/retry.
- Open Voice Browser saved previews.
- Test ElevenLabs connection.
- Close the app with dialogs and audio open.
- Launch the portable package.

## Packaging

- Run `.\scripts\build.ps1`.
- Confirm the unsigned portable ZIP exists under `artifacts/package/`.
- Confirm secrets, reports, output, databases, caches, logs, tests, and virtual environments are excluded.
