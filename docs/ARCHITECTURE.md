# Architecture

S Talking keeps UI, project orchestration, persistence, and text-to-speech
providers separated.

## GUI

`app.gui.main` owns PySide widgets, menus, and user interaction. It delegates
project lifecycle work to `ProjectManager` and does not issue raw SQL.

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
