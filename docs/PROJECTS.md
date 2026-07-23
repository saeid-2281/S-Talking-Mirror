# Projects

S Talking projects are still saved as UTF-8 `.stproj` JSON files, and existing
project files remain loadable. The Project Manager also mirrors metadata to the
SQLite `projects` table for recent-project tracking.

## Lifecycle

- New projects start with a name, optional CSV path, optional output folder, and
  the `mock` provider.
- Unsaved projects have a SQLite project record but no `project_file`.
- Save and Save As write atomically through a temporary file followed by replace.
- Save As suggests a `.stproj` filename from the project name, sanitizing only
  Windows-invalid characters while preserving allowed Unicode.
- Opening a legacy `.stproj` file creates or updates its SQLite metadata and
  updates `last_opened_at`.
- CSV paths selected during New Project, Open Project, or Browse CSV load the
  queue automatically. Reload CSV remains available for refreshing modified
  files.
- Dashboard cards update immediately after project changes, CSV loading,
  generation progress, completion, failure, and project close.
- Missing CSV or output paths are reported as warnings and do not prevent the
  project from opening.

## Settings And Credentials

- TTS provider settings are project-scoped and saved in `.stproj` files.
- API keys are credentials, not project configuration, and are not written to
  project files.
- Existing `settings.json` remains the fallback for new projects and secure
  credentials.
- Save as global defaults is an explicit action; ordinary project edits do not
  overwrite global defaults.

## Autosave

The GUI uses a 30-second `QTimer`. Autosave runs only when the current project is
dirty, has a project file, and generation is not active.

## Recent Projects

Recent projects come from `ProjectRepository.list_recent`. The dialog shows the
project name, file path, provider, and last-opened date. Removing an entry clears
its recent marker in SQLite and does not delete the `.stproj` file.

## Reports

Each generation run writes a shareable report under `reports/`. See
`docs/REPORTS.md` for file names, diagnostics export, and redaction behavior.
