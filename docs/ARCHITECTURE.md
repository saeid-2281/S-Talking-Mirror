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
cache directory, default output directory, reports directory, and artifacts
directory. Runtime directories are created from bootstrap/container construction
rather than module import.

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

`app.gui.dialogs.report_dialog` shows non-modal generation report actions.

`app.gui.developer_tools` owns GUI-triggered self-check, diagnostics, runtime
path display, spinbox demo, and prepare-commit actions so normal users do not
need PowerShell. Its Development Assistant window exposes development status,
background checks, diagnostics, runtime information, and safe Git actions only
when the Developer Tools menu is opened.

`app.gui.command_palette` provides the `Ctrl+Shift+P` keyboard command surface.
It receives command descriptors from `MainWindow` and does not duplicate project
or generation logic.

## Controllers

`app.controllers.project_controller.ProjectController` coordinates project
actions and autosave decisions through `ProjectManager`.

`app.controllers.generation_controller.GenerationController` owns
`GenerationWorker` and `QThread` lifetime, exposes progress/log/completion
signals, owns loaded jobs, paused state, active generation state, and the
current project key.

`app.controllers.settings_controller.SettingsController` owns global settings
load/save and suppresses dirty-state updates while widget values are loaded
programmatically. It also maps view-facing settings values to `AppSettings` and
keeps project-scoped settings separate from explicit global defaults.

## Project Manager

`app.services.project_manager.ProjectManager` owns project state, `.stproj`
loading/saving, recent-project metadata, autosave decisions, and SQLite
synchronization through repositories. It strips API keys from project files and
combines project configuration with secure global credentials when loading.

`app.services.statistics_service.StatisticsService` calculates dashboard cards
from generation jobs and historical durations.

`app.services.report_service.ReportService` writes generation reports,
sanitized diagnostics, and diagnostic ZIP bundles.

`app.services.diagnostics_service.DiagnosticsService` assembles complete
shareable diagnostics ZIP files from environment, application state, Git state,
latest check artifacts, latest report, logs, sanitized settings, errors, and a
manifest.

`app.services.git_service.GitService` wraps Git subprocess calls with argument
lists and blocks destructive or unsafe operations.

`app.services.desktop_service.DesktopService` owns desktop integration for
opening files/folders, launching VS Code, and copying text to the clipboard.

`app.services.task_prompt_service.TaskPromptService` loads and updates markdown
task prompts stored under `docs/tasks/`.

`app.services.provider_identity_service.ProviderIdentityService` owns
user-facing provider names and neutral provider identity metadata. Persisted
provider IDs remain unchanged.

`app.services.provider_readiness_service.ProviderReadinessService` creates the
machine-readable readiness matrix used by Preflight and Developer Tools. It
distinguishes registered adapters, missing optional dependencies, setup
requirements, partial implementations, and live-verification status.

`app.services.output_validation_service.OutputValidationService` validates
provider audio bytes before atomic finalization so empty responses or
HTML/JSON/text error bodies are not saved as audio files.

`app.services.health_service.HealthService` separates source Development
Health from packaged Runtime Health. Git, pytest, Ruff, and source compile
checks are not applicable in frozen/portable builds and do not reduce packaged
runtime health.

## Models

`app.models.domain` contains user-facing domain models such as `AppSettings` and
`TTSJob`. `app.models.project_state` contains the active GUI project state.
`app.models.ui_state` contains view-facing generation and settings state.
`app.models.dashboard_state` and `app.models.generation_report` contain
dashboard and report data transfer models.
`app.models.persistence` contains SQLite row records.

## Database And Repositories

`app.database` initializes SQLite, applies migrations, and exposes safe
transactions. `app.repositories` contains repository classes so widgets and
providers do not contain database SQL.

## Providers

`app.providers` contains Mock, ElevenLabs, OpenAI Speech, Piper, and optional
Azure, Google, Amazon Polly, and Kokoro adapters. Queue execution still uses
the existing provider factory and has not been migrated to repositories.
