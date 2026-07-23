# Architecture

S Talking keeps UI, project orchestration, persistence, and text-to-speech
providers separated.

## Bootstrap

`app.bootstrap` initializes application dependencies, including the SQLite
database, `ProjectManager`, controllers, and notification service. The GUI entry
point constructs `MainWindow` from this context.

## GUI

`app.gui.main` owns PySide widgets, menus, timers, and presentation updates. It
delegates project, generation, and settings orchestration to injected
controllers and does not issue raw SQL.

`app.gui.notifications` wraps `QMessageBox` behind a small notification
abstraction so controllers stay independent of Qt dialogs.

## Controllers

`app.controllers.project_controller.ProjectController` coordinates project
actions and autosave decisions through `ProjectManager`.

`app.controllers.generation_controller.GenerationController` owns
`GenerationWorker` and `QThread` lifetime, exposes progress/log/completion
signals, and tracks active generation state.

`app.controllers.settings_controller.SettingsController` owns global settings
load/save and suppresses dirty-state updates while widget values are loaded
programmatically.

## Project Manager

`app.services.project_manager.ProjectManager` owns project state, `.stproj`
loading/saving, recent-project metadata, autosave decisions, and SQLite
synchronization through repositories.

## Models

`app.models.domain` contains user-facing domain models such as `AppSettings` and
`TTSJob`. `app.models.project_state` contains the active GUI project state.
`app.models.persistence` contains SQLite row records.

## Database And Repositories

`app.database` initializes SQLite, applies migrations, and exposes safe
transactions. `app.repositories` contains repository classes so widgets and
providers do not contain database SQL.

## Providers

`app.providers` contains Mock, ElevenLabs, and Piper text-to-speech providers.
Queue execution still uses the existing provider factory and has not been
migrated to repositories.
