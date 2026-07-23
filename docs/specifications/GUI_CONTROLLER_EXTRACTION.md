# GUI Controller Extraction Specification

Status: Approved for implementation
Target version: 0.4.x
Branch: refactor/gui-controllers

## Purpose

Reduce MainWindow responsibilities by extracting orchestration and state-handling
logic into testable controllers, without changing user-visible behavior.

## Goals

- Keep MainWindow focused on widget construction and presentation.
- Extract project workflow orchestration.
- Extract generation workflow orchestration.
- Extract settings synchronization.
- Introduce dependency injection for ProjectManager and controllers.
- Remove database initialization from GUI modules.
- Preserve every current feature and keyboard shortcut.
- Make future MVVM migration incremental rather than disruptive.

## Non-goals

- No UI redesign.
- No Voice Browser.
- No Audio Player.
- No new providers.
- No queue migration.
- No replacement of PySide6.
- No changes to project-file format or database schema.

## Target additions

app/bootstrap.py

app/controllers/
├── __init__.py
├── project_controller.py
├── generation_controller.py
└── settings_controller.py

app/gui/
├── main.py
└── notifications.py

## Bootstrap

Create an application bootstrap layer responsible for:

- initializing the database
- constructing repositories
- constructing ProjectManager
- constructing controllers
- injecting dependencies into MainWindow

`app.gui.main` must not import database initialization functions.

Expected startup flow:

main()
→ create_application_context()
→ construct MainWindow(dependencies)
→ show window

## MainWindow constructor

MainWindow must receive dependencies rather than instantiate them internally.

Example shape:

MainWindow(
    project_controller=...,
    generation_controller=...,
    settings_controller=...,
    notification_service=...,
)

Do not require this exact signature if a single ApplicationContext object is cleaner.

## ProjectController

Responsibilities:

- new project
- open project
- save
- save as
- close
- recent projects
- update CSV path
- update output path
- update provider
- autosave coordination
- path-validation presentation data
- expose current project and dirty state

ProjectController must call ProjectManager.
It must not execute raw SQL.

## GenerationController

Responsibilities:

- validate whether generation may start
- construct and control GenerationWorker/QThread
- pause
- resume
- stop
- track generation-active state
- emit progress/log/completion/error signals

MainWindow must not directly construct QThread or GenerationWorker after extraction.

## SettingsController

Responsibilities:

- load global settings
- save global settings
- collect/apply provider settings through a view-facing data object
- mark project dirty when settings meaningfully change
- prevent false dirty-state changes while loading a project into widgets

Use a guard/context manager or explicit loading-state flag.

## Notifications

Create a thin notification abstraction for:

- information
- warning
- error
- confirmation

A Qt implementation may wrap QMessageBox.

Controllers should return structured results or raise application errors.
They must not directly call QMessageBox.

## MainWindow responsibilities after refactor

MainWindow may:

- create widgets
- connect widget signals to controller methods
- render controller state
- update labels/tables/progress
- display notifications through the injected notification service
- forward user input

MainWindow should not:

- initialize SQLite
- instantiate ProjectManager
- instantiate repositories
- construct GenerationWorker
- construct QThread
- implement project save/open business rules
- contain database knowledge

## apply_project_state decomposition

Split project-state application into focused methods:

- apply_project_paths(...)
- apply_provider_settings(...)
- apply_project_metadata(...)
- refresh_project_title(...)
- show_path_warnings(...)

Loading values into widgets must not mark the project dirty.

## Autosave

Keep QTimer in the Qt integration layer, but autosave decisions belong to
ProjectController/ProjectManager.

The controller must receive whether generation is active.

## Compatibility requirements

These commands must continue working:

python -m app.gui.main
python -m app.cli

All existing Project Manager behavior must remain unchanged.

## Tests

Add tests for:

- application bootstrap constructs dependencies
- MainWindow accepts injected dependencies
- GUI import does not initialize a database as an import side effect
- ProjectController delegates to ProjectManager
- SettingsController suppresses dirty state during programmatic loads
- Settings changes mark an open project dirty
- GenerationController starts Mock generation
- GenerationController pause/resume/stop methods delegate correctly
- generation-active state is accurate
- controllers do not import QMessageBox
- MainWindow does not instantiate ProjectManager
- MainWindow does not directly instantiate QThread or GenerationWorker
- current GUI tests continue passing
- all existing tests continue passing

## Quality requirements

- Python 3.11+
- full type hints on new public APIs
- concise docstrings
- no raw SQL outside database/repository layers
- no API keys or generated files committed
- Ruff clean
- all tests pass
- compileall passes

## Acceptance criteria

- MainWindow user-visible behavior is unchanged.
- GUI launches.
- Mock generation works.
- Project creation/open/save/recent/autosave work.
- Existing tests pass.
- New controller tests pass.
- MainWindow has substantially less orchestration logic.
- Database initialization occurs only through bootstrap.
