from __future__ import annotations

from dataclasses import dataclass

from app.controllers import GenerationController, ProjectController, SettingsController
from app.database import initialize_default_database
from app.gui.notifications import QtNotificationService
from app.services.project_manager import ProjectManager


@dataclass
class ApplicationContext:
    project_controller: ProjectController
    generation_controller: GenerationController
    settings_controller: SettingsController
    notification_service: QtNotificationService


def create_application_context() -> ApplicationContext:
    """Build GUI dependencies and initialize persistence."""
    initialize_default_database()
    project_manager = ProjectManager()
    return ApplicationContext(
        project_controller=ProjectController(project_manager),
        generation_controller=GenerationController(),
        settings_controller=SettingsController(),
        notification_service=QtNotificationService(),
    )
