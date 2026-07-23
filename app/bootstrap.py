from __future__ import annotations

from dataclasses import dataclass

from app.controllers import GenerationController, ProjectController, SettingsController
from app.container import ServiceContainer, create_service_container
from app.gui.notifications import QtNotificationService
from app.services.diagnostics_service import DiagnosticsService
from app.services.git_service import GitService
from app.services.report_service import ReportService
from app.services.statistics_service import StatisticsService
from app.services.task_prompt_service import TaskPromptService


@dataclass
class ApplicationContext:
    container: ServiceContainer
    project_controller: ProjectController
    generation_controller: GenerationController
    settings_controller: SettingsController
    notification_service: QtNotificationService
    statistics_service: StatisticsService
    report_service: ReportService
    git_service: GitService
    diagnostics_service: DiagnosticsService
    task_prompt_service: TaskPromptService


def create_application_context(container: ServiceContainer | None = None) -> ApplicationContext:
    """Build GUI dependencies from the service container."""
    services = container or create_service_container()
    return ApplicationContext(
        container=services,
        project_controller=services.project_controller,
        generation_controller=services.generation_controller,
        settings_controller=services.settings_controller,
        notification_service=services.notification_service,
        statistics_service=services.statistics_service,
        report_service=services.report_service,
        git_service=services.git_service,
        diagnostics_service=services.diagnostics_service,
        task_prompt_service=services.task_prompt_service,
    )
