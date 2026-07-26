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
    ProjectSourceRepository,
    VoiceRepository,
)
from app.services.project_manager import ProjectManager
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
from app.services.preview_service import PreviewService
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.provider_verification_service import ProviderVerificationService
from app.services.report_service import ReportService
from app.services.release_readiness_service import ReleaseReadinessService
from app.services.statistics_service import StatisticsService
from app.services.startup_recovery_service import SessionRestoreService, StartupRecoveryService
from app.services.source_import_service import SourceImportService
from app.services.task_prompt_service import TaskPromptService
from app.services.voice_service import VoiceService
from app.services.secure_credentials import SecureCredentialStore


@dataclass
class ServiceContainer:
    """Constructs and exposes application services."""

    runtime: RuntimeConfig
    database: Database
    project_repository: ProjectRepository
    source_repository: ProjectSourceRepository
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
    preflight_service: PreflightService
    preview_service: PreviewService
    startup_recovery_service: StartupRecoveryService
    session_restore_service: SessionRestoreService


def create_service_container(runtime: RuntimeConfig | None = None) -> ServiceContainer:
    """Create services from one runtime configuration."""
    config = runtime or RuntimeConfig.from_root()
    config.ensure_directories()
    database = Database(config.database_path)
    database.initialize()
    project_repository = ProjectRepository(database)
    source_repository = ProjectSourceRepository(database)
    job_repository = JobRepository(database)
    voice_repository = VoiceRepository(database)
    settings_controller = SettingsController(settings_path=config.settings_path)
    settings_dir = config.settings_path.parent
    credential_store = SecureCredentialStore(settings_dir / "credentials")
    api_profile_service = ApiProfileService(settings_dir / "api-profiles.json", credential_store)
    pronunciation_dictionary_service = PronunciationDictionaryService(settings_dir / "pronunciation-dictionaries")
    generation_scope_service = GenerationScopeService()
    source_import_service = SourceImportService()
    generation_confirmation_service = GenerationConfirmationCoordinator()
    git_service = GitService(config.app_root)
    report_service = ReportService(config)
    project_manager = ProjectManager(
        project_repository=project_repository,
        secure_settings_provider=settings_controller.load_global_settings,
    )
    diagnostics_service = DiagnosticsService(config, report_service, git_service)
    preview_service = PreviewService(config.cache_dir / "voice-previews" / "index.json")
    voice_service = VoiceService(voice_repository, config.cache_dir / "voice-previews", preview_service)
    provider_verification_service = ProviderVerificationService(config, voice_service)
    startup_recovery_service = StartupRecoveryService(config, database, job_repository, project_repository)
    session_restore_service = SessionRestoreService(config)
    preflight_service = PreflightService(config, voice_repository, voice_service)
    release_readiness_service = ReleaseReadinessService(
        config,
        database,
        git_service,
        report_service,
        diagnostics_service,
        preflight_service,
        voice_service,
    )
    return ServiceContainer(
        runtime=config,
        database=database,
        project_repository=project_repository,
        source_repository=source_repository,
        job_repository=job_repository,
        history_repository=HistoryRepository(database),
        voice_repository=voice_repository,
        cache_repository=CacheRepository(),
        project_manager=project_manager,
        project_controller=ProjectController(project_manager, config),
        generation_controller=GenerationController(
            database_path=config.legacy_database_path,
            job_repository=job_repository,
        ),
        settings_controller=settings_controller,
        notification_service=QtNotificationService(),
        statistics_service=StatisticsService(config.legacy_database_path),
        report_service=report_service,
        release_readiness_service=release_readiness_service,
        git_service=git_service,
        diagnostics_service=diagnostics_service,
        task_prompt_service=TaskPromptService(config.app_root),
        desktop_service=DesktopService(),
        health_service=HealthService(config, git_service, report_service, diagnostics_service),
        voice_service=voice_service,
        generation_monitor_service=GenerationMonitorService(),
        audio_player_service=AudioPlayerService(),
        api_profile_service=api_profile_service,
        generation_scope_service=generation_scope_service,
        source_import_service=source_import_service,
        generation_confirmation_service=generation_confirmation_service,
        pronunciation_dictionary_service=pronunciation_dictionary_service,
        provider_verification_service=provider_verification_service,
        preflight_service=preflight_service,
        preview_service=preview_service,
        startup_recovery_service=startup_recovery_service,
        session_restore_service=session_restore_service,
    )
