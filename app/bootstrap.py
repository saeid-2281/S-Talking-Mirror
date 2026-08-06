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
from app.services.generation_artifact_retention_service import GenerationArtifactRetentionService
from app.services.generation_execution_receipt_service import GenerationExecutionReceiptService
from app.services.generation_estimate_actual_service import GenerationEstimateActualService
from app.services.generation_execution_session_service import GenerationExecutionSessionService
from app.services.generation_safe_resume_service import GenerationSafeResumeService
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService
from app.services.generation_cost_capacity_service import GenerationCostCapacityService
from app.services.generation_budget_guard_service import GenerationBudgetGuardService
from app.services.generation_scope_service import GenerationScopeService
from app.services.generation_maintenance_service import GenerationMaintenanceService
from app.services.generation_monitor_service import GenerationMonitorService
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
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.product_activity_service import ProductActivityService
from app.services.activity_timeline_service import ActivityTimelineService
from app.services.notification_center_service import NotificationCenterService
from app.services.workspace_profile_service import WorkspaceProfileService
from app.services.provider_verification_service import ProviderVerificationService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_identity_service import ProviderIdentityService
from app.services.provider_readiness_service import ProviderReadinessService
from app.services.report_service import ReportService
from app.services.release_readiness_service import ReleaseReadinessService
from app.services.release_candidate_service import ReleaseCandidateService
from app.services.distribution_readiness_service import DistributionReadinessService
from app.services.final_release_service import FinalReleaseService
from app.services.upgrade_recovery_service import UpgradeRecoveryService
from app.services.update_delivery_service import UpdateDeliveryService
from app.services.crash_recovery_service import CrashRecoveryService
from app.services.performance_stability_service import PerformanceStabilityService
from app.services.security_supply_chain_service import SecuritySupplyChainService
from app.services.ux_accessibility_certification_service import UxAccessibilityCertificationService
from app.services.production_release_certification_service import ProductionReleaseCertificationService
from app.services.incident_support_service import IncidentSupportService
from app.services.incident_prevention_service import IncidentPreventionService
from app.services.prevention_effectiveness_service import PreventionEffectivenessService
from app.services.reliability_assurance_service import ReliabilityAssuranceService
from app.services.reliability_assurance_renewal_service import (
    ReliabilityAssuranceRenewalService,
)
from app.services.service_continuity_service import ServiceContinuityService
from app.services.incident_resolution_service import IncidentResolutionService
from app.services.incident_triage_service import IncidentTriageService
from app.services.post_ga_maintenance_service import PostGaMaintenanceService
from app.services.stable_release_promotion_service import StableReleasePromotionService
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
    release_candidate_service: ReleaseCandidateService
    distribution_readiness_service: DistributionReadinessService
    final_release_service: FinalReleaseService
    upgrade_recovery_service: UpgradeRecoveryService
    update_delivery_service: UpdateDeliveryService
    crash_recovery_service: CrashRecoveryService
    performance_stability_service: PerformanceStabilityService
    security_supply_chain_service: SecuritySupplyChainService
    ux_accessibility_certification_service: UxAccessibilityCertificationService
    production_release_certification_service: ProductionReleaseCertificationService
    stable_release_promotion_service: StableReleasePromotionService
    post_ga_maintenance_service: PostGaMaintenanceService
    incident_support_service: IncidentSupportService
    incident_triage_service: IncidentTriageService
    incident_resolution_service: IncidentResolutionService
    incident_prevention_service: IncidentPreventionService
    prevention_effectiveness_service: PreventionEffectivenessService
    reliability_assurance_service: ReliabilityAssuranceService
    reliability_assurance_renewal_service: ReliabilityAssuranceRenewalService
    service_continuity_service: ServiceContinuityService
    git_service: GitService
    diagnostics_service: DiagnosticsService
    task_prompt_service: TaskPromptService
    desktop_service: DesktopService
    health_service: HealthService
    voice_service: VoiceService
    generation_maintenance_service: GenerationMaintenanceService
    generation_artifact_retention_service: GenerationArtifactRetentionService
    generation_monitor_service: GenerationMonitorService
    generation_history_service: GenerationHistoryService
    generation_cost_capacity_service: GenerationCostCapacityService
    generation_budget_guard_service: GenerationBudgetGuardService
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
    generation_estimate_actual_service: GenerationEstimateActualService
    generation_execution_session_service: GenerationExecutionSessionService
    generation_safe_resume_service: GenerationSafeResumeService
    pronunciation_dictionary_service: PronunciationDictionaryService
    provider_verification_service: ProviderVerificationService
    provider_catalog_service: ProviderCatalogService
    provider_identity_service: ProviderIdentityService
    provider_readiness_service: ProviderReadinessService
    product_activity_service: ProductActivityService
    notification_center_service: NotificationCenterService
    activity_timeline_service: ActivityTimelineService
    workspace_profile_service: WorkspaceProfileService
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
        release_candidate_service=services.release_candidate_service,
        distribution_readiness_service=services.distribution_readiness_service,
        final_release_service=services.final_release_service,
        upgrade_recovery_service=services.upgrade_recovery_service,
        update_delivery_service=services.update_delivery_service,
        crash_recovery_service=services.crash_recovery_service,
        performance_stability_service=services.performance_stability_service,
        security_supply_chain_service=services.security_supply_chain_service,
        ux_accessibility_certification_service=services.ux_accessibility_certification_service,
        production_release_certification_service=services.production_release_certification_service,
        stable_release_promotion_service=services.stable_release_promotion_service,
        post_ga_maintenance_service=services.post_ga_maintenance_service,
        incident_support_service=services.incident_support_service,
        incident_triage_service=services.incident_triage_service,
        incident_resolution_service=services.incident_resolution_service,
        incident_prevention_service=services.incident_prevention_service,
        prevention_effectiveness_service=services.prevention_effectiveness_service,
        reliability_assurance_service=services.reliability_assurance_service,
        reliability_assurance_renewal_service=(
            services.reliability_assurance_renewal_service
        ),
        service_continuity_service=services.service_continuity_service,
        git_service=services.git_service,
        diagnostics_service=services.diagnostics_service,
        task_prompt_service=services.task_prompt_service,
        desktop_service=services.desktop_service,
        health_service=services.health_service,
        voice_service=services.voice_service,
        generation_maintenance_service=services.generation_maintenance_service,
        generation_artifact_retention_service=services.generation_artifact_retention_service,
        generation_monitor_service=services.generation_monitor_service,
        generation_history_service=services.generation_history_service,
        generation_cost_capacity_service=services.generation_cost_capacity_service,
        generation_budget_guard_service=services.generation_budget_guard_service,
        generation_incident_service=services.generation_incident_service,
        generation_problem_service=services.generation_problem_service,
        generation_remediation_automation_service=(
            services.generation_remediation_automation_service
        ),
        generation_performance_service=services.generation_performance_service,
        generation_performance_policy_service=services.generation_performance_policy_service,
        generation_reliability_service=services.generation_reliability_service,
        generation_recovery_service=services.generation_recovery_service,
        audio_player_service=services.audio_player_service,
        api_profile_service=services.api_profile_service,
        generation_scope_service=services.generation_scope_service,
        source_import_service=services.source_import_service,
        generation_confirmation_service=services.generation_confirmation_service,
        generation_launch_receipt_service=services.generation_launch_receipt_service,
        generation_execution_receipt_service=services.generation_execution_receipt_service,
        generation_estimate_actual_service=services.generation_estimate_actual_service,
        generation_execution_session_service=services.generation_execution_session_service,
        generation_safe_resume_service=services.generation_safe_resume_service,
        pronunciation_dictionary_service=services.pronunciation_dictionary_service,
        provider_verification_service=services.provider_verification_service,
        provider_catalog_service=services.provider_catalog_service,
        provider_identity_service=services.provider_identity_service,
        provider_readiness_service=services.provider_readiness_service,
        product_activity_service=services.product_activity_service,
        notification_center_service=services.notification_center_service,
        activity_timeline_service=services.activity_timeline_service,
        workspace_profile_service=services.workspace_profile_service,
        preflight_service=services.preflight_service,
        startup_recovery_service=services.startup_recovery_service,
        session_restore_service=services.session_restore_service,
    )
