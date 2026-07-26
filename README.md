# S Talking v0.17.1-rc2
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

Inside the app, open Developer Tools > Development Assistant for the same
workflow plus task prompts, Git status, safe commit preparation, branch push
confirmation, smoke testing, and PR-description copying.

Use `Ctrl+Shift+P` to open the Command Palette for keyboard-first access to
project, generation, report, and developer actions.

Advanced terminal commands are documented in `docs/DEVELOPER_TOOLS.md`.

## Documentation

- User guide: `docs/USER_GUIDE.md`
- Installation: `docs/INSTALLATION.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Release checklist: `docs/RELEASE_CHECKLIST.md`
- Project behavior: `docs/PROJECTS.md`
- Multi-source projects: `docs/MULTI_SOURCE_PROJECTS.md`
- Provider setup: `docs/PROVIDERS.md`
- Provider capability matrix: `docs/PROVIDER_CAPABILITIES.md`
- v0.17 product polish scope: `docs/PRODUCT_POLISH_V017.md`
- Reports and diagnostics: `docs/REPORTS.md`
- Developer tools: `docs/DEVELOPER_TOOLS.md`
- Architecture: `docs/ARCHITECTURE.md`

## Release Candidate Checks

Run:

```powershell
.\scripts\release-check.ps1
```

Build the unsigned portable ZIP:

```powershell
.\scripts\build.ps1
```

## Health Center and Task Center

S Talking now includes a zero-terminal development overview:

- Click the health indicator in the status bar or open **Developer Tools → Health Center**.
- Use **Copy summary** for a compact update.
- Use **Copy for ChatGPT** for a structured Markdown health report.
- Open **Developer Tools → Task Center** to review tasks stored in `docs/tasks/`, copy their prompts, and update task status.

See `docs/HEALTH_CENTER.md` for details.
