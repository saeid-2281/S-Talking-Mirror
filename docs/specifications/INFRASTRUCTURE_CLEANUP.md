# Infrastructure Cleanup Specification

Status: Approved for implementation
Branch: refactor/infrastructure-cleanup
Target version: 0.4.x

## Purpose

Complete the architectural cleanup started by the GUI controller extraction.
Move remaining application state and construction concerns out of MainWindow
without changing user-visible behavior.

## Goals

- Introduce a ServiceContainer.
- Centralize application paths and runtime configuration.
- Remove hardcoded database and settings paths from controllers.
- Move generation state out of MainWindow.
- Move settings collection and application logic out of MainWindow where practical.
- Remove ProjectFile construction from MainWindow.
- Reduce MainWindow orchestration responsibilities further.
- Preserve all current functionality and tests.

## Non-goals

- No UI redesign.
- No Voice Browser.
- No Audio Player.
- No new providers.
- No database-schema changes.
- No queue persistence migration.
- No cloud functionality.

## Target additions

app/container.py
app/config/runtime.py
app/models/ui_state.py

Possible updates:

app/bootstrap.py
app/controllers/generation_controller.py
app/controllers/project_controller.py
app/controllers/settings_controller.py
app/gui/main.py
app/models/domain.py

## ServiceContainer

Create a ServiceContainer responsible for constructing and exposing:

- runtime configuration
- database
- repositories
- ProjectManager
- ProjectController
- GenerationController
- SettingsController
- NotificationService

Application bootstrap must build the ServiceContainer and then create the
ApplicationContext from it.

MainWindow must not construct services, repositories, managers, workers,
threads, or runtime paths.

## Runtime configuration

Create a typed runtime configuration model containing:

- application root
- data directory
- database path
- settings path
- log directory
- cache directory
- default output directory

Paths must be resolved from a single source.

Directories that must exist should be created during bootstrap, not during
module import.

## GenerationController cleanup

GenerationController must own:

- jobs
- paused state
- active worker
- active thread
- generation-active state
- current project key

MainWindow should not keep duplicate generation state.

Required APIs should include:

- set_jobs(...)
- clear_jobs()
- has_jobs()
- jobs
- start(...)
- pause()
- resume()
- stop()
- is_active
- is_paused

Database path must be injected through runtime configuration.

## SettingsController cleanup

Move settings composition and mapping logic out of MainWindow as far as
practical.

Introduce a view-facing settings data object if needed.

SettingsController must support:

- constructing AppSettings from view values
- returning values suitable for populating widgets
- loading global settings
- saving global settings
- dirty-state suppression
- comparison of meaningful settings changes

The GUI may still read widget values, but AppSettings construction should not
remain as a long inline MainWindow method.

## ProjectController cleanup

ProjectController should expose higher-level operations rather than being only
a one-to-one pass-through wrapper.

Move ProjectFile/project-key creation out of MainWindow.

Required behavior:

- provide project name
- provide current project key
- provide current project state
- create ad-hoc generation context when no saved project is open
- centralize fallback project behavior

## UI state

Create a small UI/generation state model if needed for:

- selected jobs
- paused state
- current project display name
- dirty marker
- generation status

Do not duplicate authoritative state across MainWindow and controllers.

## MainWindow responsibilities

MainWindow may:

- create widgets
- connect signals
- read user input
- render controller state
- update tables and progress
- invoke controller commands

MainWindow must not:

- store authoritative generation jobs
- store authoritative paused state
- construct AppSettings directly in one large method
- construct ProjectFile
- know database paths
- know settings-file paths
- instantiate controllers or services

## Bootstrap

Expected flow:

main()
→ create_service_container()
→ create_application_context(container)
→ MainWindow(context)

Bootstrap must be the only place that initializes runtime directories and
database persistence.

## Compatibility

These commands must continue working:

python -m app.gui.main
python -m app.cli

Project management, autosave, Recent Projects, settings persistence, Mock
generation, pause/resume/stop, ElevenLabs, and Piper must continue working.

## Tests

Add tests for:

- runtime configuration resolves all paths
- bootstrap creates required directories
- ServiceContainer constructs all dependencies
- database path is injected into GenerationController
- settings path is injected into SettingsController
- GenerationController owns jobs
- GenerationController owns paused state
- MainWindow does not assign self.jobs
- MainWindow does not assign self.paused
- MainWindow does not construct ProjectFile
- MainWindow does not contain hardcoded data/s-talking.db
- MainWindow does not contain hardcoded settings.json
- ProjectController returns a project key
- ad-hoc generation context works without an open project
- existing controller tests continue passing
- all existing project-manager tests continue passing
- GUI imports without side effects

## Quality requirements

- Python 3.11+
- type hints on public APIs
- concise docstrings
- no raw SQL outside database/repository modules
- no user-visible behavior change
- Ruff clean
- all tests pass
- compileall passes

## Acceptance criteria

- MainWindow is materially smaller.
- Generation state has one authoritative owner.
- Runtime paths come from one configuration object.
- Service construction is centralized.
- Existing GUI behavior remains unchanged.
- Mock generation still works.
- All tests pass.
