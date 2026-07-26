from __future__ import annotations

from dataclasses import dataclass

from app.controllers import GenerationController, ProjectController, SettingsController
from app.container import ServiceContainer, create_service_container
from app.repositories import ProjectSourceRepository
from app.gui.notifications import QtNotificationService
from app.services.diagnostics_service import DiagnosticsService
from app.services.desktop_service import DesktopService
from app.services.audio_player_service import AudioPlayerService
from app.services.api_profile_service import ApiProfileService
from app.services.git_service import GitService
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_scope_service import GenerationScopeService
from app.services.generation_monitor_service import GenerationMonitorService
from app.services.health_service import HealthService
from app.services.preflight_service import PreflightService
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.product_activity_service import ProductActivityService
from app.services.provider_verification_service import ProviderVerificationService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_identity_service import ProviderIdentityService
from app.services.provider_readiness_service import ProviderReadinessService
from app.services.report_service import ReportService
from app.services.release_readiness_service import ReleaseReadinessService
from app.services.statistics_service import StatisticsService
from app.services.startup_recovery_service import SessionRestoreService, StartupRecoveryService
from app.services.source_import_service import SourceImportService
from app.services.task_prompt_service import TaskPromptService
from app.services.voice_service import VoiceService


@dataclass
class ApplicationContext:
    container: ServiceContainer
    source_repository: ProjectSourceRepository
    project_controller: ProjectController
    generation_controller: GenerationController
    settings_controller: SettingsController
    notification_service: QtNotificationService
    statistics_service: StatisticsService
    report_service: ReportService
    release_readiness_service: ReleaseReadinessService
    git_service: GitService
    diagnostics_service: DiagnosticsService
    task_prompt_service: TaskPromptService
    desktop_service: DesktopService
    health_service: HealthService
    voice_service: VoiceService
    generation_monitor_service: GenerationMonitorService
    audio_player_service: AudioPlayerService
    api_profile_service: ApiProfileService
    generation_scope_service: GenerationScopeService
    source_import_service: SourceImportService
    generation_confirmation_service: GenerationConfirmationCoordinator
    pronunciation_dictionary_service: PronunciationDictionaryService
    provider_verification_service: ProviderVerificationService
    provider_catalog_service: ProviderCatalogService
    provider_identity_service: ProviderIdentityService
    provider_readiness_service: ProviderReadinessService
    product_activity_service: ProductActivityService
    preflight_service: PreflightService
    startup_recovery_service: StartupRecoveryService
    session_restore_service: SessionRestoreService


def create_application_context(container: ServiceContainer | None = None) -> ApplicationContext:
    """Build GUI dependencies from the service container."""
    services = container or create_service_container()
    return ApplicationContext(
        container=services,
        source_repository=services.source_repository,
        project_controller=services.project_controller,
        generation_controller=services.generation_controller,
        settings_controller=services.settings_controller,
        notification_service=services.notification_service,
        statistics_service=services.statistics_service,
        report_service=services.report_service,
        release_readiness_service=services.release_readiness_service,
        git_service=services.git_service,
        diagnostics_service=services.diagnostics_service,
        task_prompt_service=services.task_prompt_service,
        desktop_service=services.desktop_service,
        health_service=services.health_service,
        voice_service=services.voice_service,
        generation_monitor_service=services.generation_monitor_service,
        audio_player_service=services.audio_player_service,
        api_profile_service=services.api_profile_service,
        generation_scope_service=services.generation_scope_service,
        source_import_service=services.source_import_service,
        generation_confirmation_service=services.generation_confirmation_service,
        pronunciation_dictionary_service=services.pronunciation_dictionary_service,
        provider_verification_service=services.provider_verification_service,
        provider_catalog_service=services.provider_catalog_service,
        provider_identity_service=services.provider_identity_service,
        provider_readiness_service=services.provider_readiness_service,
        product_activity_service=services.product_activity_service,
        preflight_service=services.preflight_service,
        startup_recovery_service=services.startup_recovery_service,
        session_restore_service=services.session_restore_service,
    )
