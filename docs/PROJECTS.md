# Projects

S Talking projects are still saved as UTF-8 `.stproj` JSON files, and existing
project files remain loadable. The Project Manager also mirrors metadata to the
SQLite `projects` table for recent-project tracking.

## Lifecycle

- New projects start with a name, optional CSV path, optional output folder, and
  the `mock` provider.
- Unsaved projects have a SQLite project record but no `project_file`.
- Save and Save As write atomically through a temporary file followed by replace.
- Opening a legacy `.stproj` file creates or updates its SQLite metadata and
  updates `last_opened_at`.
- Missing CSV or output paths are reported as warnings and do not prevent the
  project from opening.

## Autosave

The GUI uses a 30-second `QTimer`. Autosave runs only when the current project is
dirty, has a project file, and generation is not active.

## Recent Projects

Recent projects come from `ProjectRepository.list_recent`. The dialog shows the
project name, file path, provider, and last-opened date. Removing an entry clears
its recent marker in SQLite and does not delete the `.stproj` file.
