from __future__ import annotations

from dataclasses import dataclass

from app.config.runtime import RuntimeConfig
from app.controllers import GenerationController, ProjectController, SettingsController
from app.database.connection import Database
from app.gui.notifications import QtNotificationService
from app.repositories import (
    CacheRepository,
    HistoryRepository,
    JobRepository,
    ProjectRepository,
    VoiceRepository,
)
from app.services.project_manager import ProjectManager
from app.services.diagnostics_service import DiagnosticsService
from app.services.desktop_service import DesktopService
from app.services.git_service import GitService
from app.services.report_service import ReportService
from app.services.statistics_service import StatisticsService
from app.services.task_prompt_service import TaskPromptService


@dataclass
class ServiceContainer:
    """Constructs and exposes application services."""

    runtime: RuntimeConfig
    database: Database
    project_repository: ProjectRepository
    job_repository: JobRepository
    history_repository: HistoryRepository
    voice_repository: VoiceRepository
    cache_repository: CacheRepository
    project_manager: ProjectManager
    project_controller: ProjectController
    generation_controller: GenerationController
    settings_controller: SettingsController
    notification_service: QtNotificationService
    statistics_service: StatisticsService
    report_service: ReportService
    git_service: GitService
    diagnostics_service: DiagnosticsService
    task_prompt_service: TaskPromptService
    desktop_service: DesktopService


def create_service_container(runtime: RuntimeConfig | None = None) -> ServiceContainer:
    """Create services from one runtime configuration."""
    config = runtime or RuntimeConfig.from_root()
    config.ensure_directories()
    database = Database(config.database_path)
    database.initialize()
    project_repository = ProjectRepository(database)
    settings_controller = SettingsController(settings_path=config.settings_path)
    git_service = GitService(config.app_root)
    report_service = ReportService(config)
    project_manager = ProjectManager(
        project_repository=project_repository,
        secure_settings_provider=settings_controller.load_global_settings,
    )
    return ServiceContainer(
        runtime=config,
        database=database,
        project_repository=project_repository,
        job_repository=JobRepository(database),
        history_repository=HistoryRepository(database),
        voice_repository=VoiceRepository(database),
        cache_repository=CacheRepository(),
        project_manager=project_manager,
        project_controller=ProjectController(project_manager, config),
        generation_controller=GenerationController(database_path=config.legacy_database_path),
        settings_controller=settings_controller,
        notification_service=QtNotificationService(),
        statistics_service=StatisticsService(config.legacy_database_path),
        report_service=report_service,
        git_service=git_service,
        diagnostics_service=DiagnosticsService(config, report_service, git_service),
        task_prompt_service=TaskPromptService(config.app_root),
        desktop_service=DesktopService(),
    )
