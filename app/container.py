from __future__ import annotations

from dataclasses import dataclass

from app.config.runtime import RuntimeConfig
from app.controllers import GenerationController, ProjectController, SettingsController
from app.database.connection import Database
from app.gui.notifications import QtNotificationService
from app.repositories import (
    CacheRepository,
    GenerationMaintenanceRepository,
    GenerationOrchestrationRepository,
    HistoryRepository,
    JobRepository,
    ProductEventRepository,
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
from app.services.generation_execution_receipt_service import GenerationExecutionReceiptService
from app.services.generation_execution_session_service import GenerationExecutionSessionService
from app.services.generation_safe_resume_service import GenerationSafeResumeService
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService
from app.services.generation_cost_capacity_service import GenerationCostCapacityService
from app.services.generation_scope_service import GenerationScopeService
from app.services.generation_maintenance_service import GenerationMaintenanceService
from app.services.generation_monitor_service import GenerationMonitorService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.generation_history_service import GenerationHistoryService
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_problem_service import GenerationProblemService
from app.services.generation_remediation_automation_service import (
    GenerationRemediationAutomationService,
)
from app.services.generation_performance_policy_service import (
    GenerationPerformancePolicyService,
)
from app.services.generation_performance_service import GenerationPerformanceService
from app.services.generation_reliability_service import GenerationReliabilityService
from app.services.generation_recovery_service import GenerationRecoveryService
from app.services.health_service import HealthService
from app.services.preflight_service import PreflightService
from app.services.preview_service import PreviewService
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.product_activity_service import ProductActivityService
from app.services.activity_timeline_service import ActivityTimelineService
from app.services.notification_center_service import NotificationCenterService
from app.services.workspace_profile_service import WorkspaceProfileService
from app.services.provider_verification_service import ProviderVerificationService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_account_catalog_store import ProviderAccountCatalogStore
from app.services.provider_identity_service import ProviderIdentityService
from app.services.provider_readiness_service import ProviderReadinessService
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
    product_event_repository: ProductEventRepository
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
    generation_maintenance_service: GenerationMaintenanceService
    generation_monitor_service: GenerationMonitorService
    generation_orchestration_service: GenerationOrchestrationService
    generation_history_service: GenerationHistoryService
    generation_cost_capacity_service: GenerationCostCapacityService
    generation_incident_service: GenerationIncidentService
    generation_problem_service: GenerationProblemService
    generation_remediation_automation_service: GenerationRemediationAutomationService
    generation_performance_service: GenerationPerformanceService
    generation_performance_policy_service: GenerationPerformancePolicyService
    generation_reliability_service: GenerationReliabilityService
    generation_recovery_service: GenerationRecoveryService
    audio_player_service: AudioPlayerService
    api_profile_service: ApiProfileService
    generation_scope_service: GenerationScopeService
    source_import_service: SourceImportService
    generation_confirmation_service: GenerationConfirmationCoordinator
    generation_launch_receipt_service: GenerationLaunchReceiptService
    generation_execution_receipt_service: GenerationExecutionReceiptService
    generation_execution_session_service: GenerationExecutionSessionService
    generation_safe_resume_service: GenerationSafeResumeService
    pronunciation_dictionary_service: PronunciationDictionaryService
    provider_verification_service: ProviderVerificationService
    provider_catalog_service: ProviderCatalogService
    provider_account_catalog_store: ProviderAccountCatalogStore
    provider_identity_service: ProviderIdentityService
    provider_readiness_service: ProviderReadinessService
    product_activity_service: ProductActivityService
    notification_center_service: NotificationCenterService
    activity_timeline_service: ActivityTimelineService
    workspace_profile_service: WorkspaceProfileService
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
    product_event_repository = ProductEventRepository(database)
    notification_center_service = NotificationCenterService(product_event_repository)
    activity_timeline_service = ActivityTimelineService(product_event_repository)
    workspace_profile_service = WorkspaceProfileService(config.settings_path.parent / "workspace-profiles.json")
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
    generation_launch_receipt_service = GenerationLaunchReceiptService(config.reports_dir)
    generation_execution_receipt_service = GenerationExecutionReceiptService(config.reports_dir)
    generation_execution_session_service = GenerationExecutionSessionService(config.reports_dir)
    generation_safe_resume_service = GenerationSafeResumeService(config.reports_dir)
    git_service = GitService(config.app_root)
    report_service = ReportService(config)
    project_manager = ProjectManager(
        project_repository=project_repository,
        secure_settings_provider=settings_controller.load_global_settings,
    )
    diagnostics_service = DiagnosticsService(config, report_service, git_service)
    preview_service = PreviewService(config.cache_dir / "voice-previews" / "index.json")
    account_catalog_store = ProviderAccountCatalogStore(config.cache_dir / "provider-account-catalogs")
    voice_service = VoiceService(
        voice_repository,
        config.cache_dir / "voice-previews",
        preview_service,
        account_catalog_store,
    )
    provider_verification_service = ProviderVerificationService(config, voice_service)
    provider_identity_service = ProviderIdentityService(config.resource_path("app", "resources", "brand"))
    provider_readiness_service = ProviderReadinessService(provider_identity_service)
    startup_recovery_service = StartupRecoveryService(config, database, job_repository, project_repository)
    session_restore_service = SessionRestoreService(config)
    generation_recovery_service = GenerationRecoveryService(config.cache_dir / "generation-recovery.json")
    generation_maintenance_repository = GenerationMaintenanceRepository(database)
    generation_maintenance_service = GenerationMaintenanceService(
        database,
        generation_maintenance_repository,
        config.artifacts_dir / "database-backups",
    )
    generation_maintenance_service.run_startup_check()
    generation_cost_capacity_service = GenerationCostCapacityService(
        product_event_repository,
        job_repository,
    )
    preflight_service = PreflightService(
        config,
        voice_repository,
        voice_service,
        provider_readiness_service=provider_readiness_service,
        cost_capacity_service=generation_cost_capacity_service,
    )
    release_readiness_service = ReleaseReadinessService(
        config,
        database,
        git_service,
        report_service,
        diagnostics_service,
        preflight_service,
        voice_service,
    )
    generation_performance_policy_service = GenerationPerformancePolicyService(
        product_event_repository
    )
    generation_performance_service = GenerationPerformanceService(
        product_event_repository,
        policy_service=generation_performance_policy_service,
    )
    generation_history_service = GenerationHistoryService(
        product_event_repository,
        generation_performance_service,
        generation_performance_policy_service,
    )
    generation_reliability_service = GenerationReliabilityService(
        product_event_repository
    )
    generation_incident_service = GenerationIncidentService(product_event_repository)
    generation_problem_service = GenerationProblemService(product_event_repository)
    generation_orchestration_service = GenerationOrchestrationService(
        GenerationOrchestrationRepository(database),
        api_profile_service,
        notification_center_service,
        activity_timeline_service,
    )
    generation_controller = GenerationController(
        database_path=config.legacy_database_path,
        job_repository=job_repository,
        orchestration_service=generation_orchestration_service,
        api_profile_service=api_profile_service,
    )
    generation_remediation_automation_service = GenerationRemediationAutomationService(
        product_event_repository,
        generation_incident_service,
        generation_problem_service,
        job_repository,
    )
    return ServiceContainer(
        runtime=config,
        database=database,
        project_repository=project_repository,
        product_event_repository=product_event_repository,
        source_repository=source_repository,
        job_repository=job_repository,
        history_repository=HistoryRepository(database),
        voice_repository=voice_repository,
        cache_repository=CacheRepository(),
        project_manager=project_manager,
        project_controller=ProjectController(project_manager, config),
        generation_controller=generation_controller,
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
        generation_maintenance_service=generation_maintenance_service,
        generation_monitor_service=GenerationMonitorService(recovery_service=generation_recovery_service),
        generation_orchestration_service=generation_orchestration_service,
        generation_history_service=generation_history_service,
        generation_cost_capacity_service=generation_cost_capacity_service,
        generation_incident_service=generation_incident_service,
        generation_problem_service=generation_problem_service,
        generation_remediation_automation_service=(
            generation_remediation_automation_service
        ),
        generation_performance_service=generation_performance_service,
        generation_performance_policy_service=generation_performance_policy_service,
        generation_reliability_service=generation_reliability_service,
        generation_recovery_service=generation_recovery_service,
        audio_player_service=AudioPlayerService(),
        api_profile_service=api_profile_service,
        generation_scope_service=generation_scope_service,
        source_import_service=source_import_service,
        generation_confirmation_service=generation_confirmation_service,
        generation_launch_receipt_service=generation_launch_receipt_service,
        generation_execution_receipt_service=generation_execution_receipt_service,
        generation_execution_session_service=generation_execution_session_service,
        generation_safe_resume_service=generation_safe_resume_service,
        pronunciation_dictionary_service=pronunciation_dictionary_service,
        provider_verification_service=provider_verification_service,
        provider_catalog_service=ProviderCatalogService(),
        provider_account_catalog_store=account_catalog_store,
        provider_identity_service=provider_identity_service,
        provider_readiness_service=provider_readiness_service,
        product_activity_service=ProductActivityService(
            product_event_repository,
            notification_center_service,
            activity_timeline_service,
            generation_performance_service,
            generation_performance_policy_service,
            generation_incident_service,
            generation_problem_service,
            generation_remediation_automation_service,
            generation_reliability_service,
            generation_cost_capacity_service,
        ),
        notification_center_service=notification_center_service,
        activity_timeline_service=activity_timeline_service,
        workspace_profile_service=workspace_profile_service,
        preflight_service=preflight_service,
        preview_service=preview_service,
        startup_recovery_service=startup_recovery_service,
        session_restore_service=session_restore_service,
    )
