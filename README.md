# S Talking v0.3

S Talking is a Windows-friendly PySide6 audio-generation tool for CSV-driven
text-to-speech batches.

## Zero-Terminal Workflow

For normal testing and use, double-click:

```text
S-Talking.cmd
```

Then:

1. Create a new project.
2. Enter a project name.
3. Select a CSV and output folder.
4. Confirm the CSV loads automatically and dashboard cards update.
5. Start generation with the `mock`, `piper`, or `elevenlabs` provider.
6. Open the generated report from the non-modal result panel.

No PowerShell, Git, pytest, Ruff, or compile commands are required for the
normal workflow.

## Highlights

- Dashboard cards for files, characters, completed, failed, and estimated time.
- Save/open `.stproj` project files with recent-project tracking.
- Automatic CSV queue loading for project creation and project opening.
- Project-scoped TTS settings with global defaults kept separate.
- Non-modal generation report panel with diagnostics export.
- SQLite job history and resume at `data/s-talking.db`.
- SQLite project metadata at `data/s_talking.db`.
- Mock, ElevenLabs, and Piper providers.

## Developer Launcher

Double-click:

```text
S-Talking-Dev.cmd
```

The launcher can run S Talking, run all checks, export diagnostics, open
reports/logs, and open the repository in VS Code.

Advanced terminal commands are documented in `docs/DEVELOPER_TOOLS.md`.

## Documentation

- Project behavior: `docs/PROJECTS.md`
- Reports and diagnostics: `docs/REPORTS.md`
- Developer tools: `docs/DEVELOPER_TOOLS.md`
- Architecture: `docs/ARCHITECTURE.md`
