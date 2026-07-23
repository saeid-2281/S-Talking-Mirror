# Developer Tools

Normal development and testing can be done without typing commands by using:

```text
S-Talking-Dev.cmd
```

The developer launcher offers:

- Run S Talking
- Run all checks
- Export diagnostics
- Open latest report
- Open logs
- Open repository in VS Code
- Exit

The GUI also has a Developer Tools menu with self-check, diagnostics export,
runtime paths, report/log/data folder openers, a spinbox visual test, and a
Prepare Commit dry run.

The top-level Developer Tools menu is always visible. Actions remain visible
when unavailable and are disabled with a tooltip explaining the missing
precondition.

## Run All Checks

Developer Tools > Run all checks opens a non-modal progress window and starts
`scripts/dev-check.ps1` with `QProcess`. The GUI remains responsive, duplicate
check launches are blocked, and a running check can be cancelled safely.

The window captures stdout, stderr, exit code, elapsed time, and a structured
result model. It offers Open artifact folder, Export diagnostics, and Copy
output actions.

## Development Assistant

Open Developer Tools > Development Assistant for a non-modal in-app development
panel. It shows:

- current branch and working tree state
- latest test/check artifact
- latest report and diagnostics ZIP
- application, Python, and Qt versions
- task prompt files from `docs/tasks/`

The assistant can run checks, launch the offscreen smoke test, export
diagnostics, open folders, copy task prompts, prepare commits, push the current
branch after confirmation, and copy a PR description.

## Command Palette

Press `Ctrl+Shift+P` to open the Command Palette. It supports substring
filtering, keyboard Up/Down navigation, Enter to execute, and Escape to close.
Commands reuse the same application actions where practical, so menu and
palette behavior stay aligned.

Command groups include Project, Generation, Reports, and Developer actions.
Commands that are not valid in the current state remain visible but disabled.

## Runtime Information

Developer Tools > Show runtime information opens a non-modal dialog with
application version, repository/runtime paths, current branch, Python
executable/version, and Qt/PySide version. It never shows API keys or
credentials.

## Check Artifacts

Self-check and the developer launcher write complete output to:

```text
artifacts/dev-check/<timestamp>/
artifacts/dev-check/latest/
```

Files include:

- `summary.txt`
- `compileall.txt`
- `pytest.txt`
- `ruff.txt`
- `environment.json`

## Advanced Terminal Use

These commands are optional for advanced developers:

```powershell
.\scripts\dev-check.ps1
.\scripts\run.ps1
.\scripts\prepare-commit.ps1
```

`Prepare Commit` never merges, force-pushes, or discards work. It creates a
dry-run preview by default.

Git automation uses subprocess argument lists, never `shell=True`, and blocks
main-branch commits, destructive commands, force operations, and generated or
secret-bearing files.
