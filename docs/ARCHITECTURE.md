# Architecture

S Talking keeps UI, project orchestration, persistence, and text-to-speech
providers separated.

## Bootstrap

`app.bootstrap` builds the GUI `ApplicationContext` from a `ServiceContainer`.
The expected startup path is `create_service_container()`,
`create_application_context(container)`, then `MainWindow(context)`.

## Runtime Configuration

`app.config.runtime.RuntimeConfig` is the single source for application paths:
application root, data directory, database paths, settings path, log directory,
cache directory, and default output directory. Runtime directories are created
from bootstrap/container construction rather than module import.

## Service Container

`app.container.ServiceContainer` centralizes construction of the runtime config,
database, repositories, `ProjectManager`, controllers, and notification service.
Controllers receive paths and services through this container instead of using
hardcoded runtime paths.

## GUI

`app.gui.main` owns PySide widgets, menus, timers, user input forwarding, and
presentation updates. It delegates project, generation, and settings
orchestration to injected controllers and does not issue raw SQL, construct
services, construct workers/threads, own generation jobs, or know database and
settings-file paths.

`app.gui.notifications` wraps `QMessageBox` behind a small notification
abstraction so controllers stay independent of Qt dialogs.

## Controllers

`app.controllers.project_controller.ProjectController` coordinates project
actions and autosave decisions through `ProjectManager`.

`app.controllers.generation_controller.GenerationController` owns
`GenerationWorker` and `QThread` lifetime, exposes progress/log/completion
signals, owns loaded jobs, paused state, active generation state, and the
current project key.

`app.controllers.settings_controller.SettingsController` owns global settings
load/save and suppresses dirty-state updates while widget values are loaded
programmatically. It also maps view-facing settings values to `AppSettings`.

## Project Manager

`app.services.project_manager.ProjectManager` owns project state, `.stproj`
loading/saving, recent-project metadata, autosave decisions, and SQLite
synchronization through repositories.

## Models

`app.models.domain` contains user-facing domain models such as `AppSettings` and
`TTSJob`. `app.models.project_state` contains the active GUI project state.
`app.models.ui_state` contains view-facing generation and settings state.
`app.models.persistence` contains SQLite row records.

## Database And Repositories

`app.database` initializes SQLite, applies migrations, and exposes safe
transactions. `app.repositories` contains repository classes so widgets and
providers do not contain database SQL.

## Providers

`app.providers` contains Mock, ElevenLabs, and Piper text-to-speech providers.
Queue execution still uses the existing provider factory and has not been
migrated to repositories.
