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

## Check Artifacts

Self-check and the developer launcher write complete output to:

```text
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
