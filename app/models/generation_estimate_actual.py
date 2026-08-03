from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationEstimateActualRun:
    """One secret-free comparison between a launch estimate and its actual run."""

    run_id: str
    project_name: str
    status: str
    provider: str
    model_id: str = ""
    voice_id: str = ""
    currency: str = "USD"
    launch_receipt_id: str = ""
    launch_receipt_path: str = ""
    execution_receipt_id: str = ""
    execution_receipt_path: str = ""
    execution_session_path: str = ""
    finished_at: str = ""
    estimated_files: int = 0
    actual_files: int = 0
    file_variance: int = 0
    file_accuracy_percent: float = 0.0
    estimated_characters: int = 0
    actual_characters: int = 0
    retry_characters: int = 0
    character_variance: int = 0
    character_accuracy_percent: float = 0.0
    estimated_requests: int = 0
    actual_requests: int = 0
    request_variance: int = 0
    request_accuracy_percent: float = 0.0
    estimated_duration_seconds: float = 0.0
    actual_duration_seconds: float = 0.0
    duration_variance_seconds: float = 0.0
    duration_accuracy_percent: float = 0.0
    duration_multiplier: float = 0.0
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    cost_variance: float = 0.0
    cost_accuracy_percent: float = 0.0
    cost_multiplier: float = 0.0
    cost_source: str = "unavailable"
    estimate_accuracy_score: float = 0.0
    retry_events: int = 0
    success_rate_percent: float = 0.0
    confidence: str = "low"
    integrity_status: str = "verified"
    attention_reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requires_attention(self) -> bool:
        return bool(self.attention_reasons)


@dataclass(frozen=True)
class GenerationEstimateActualProviderSummary:
    """Calibration and performance metrics for one provider/model/voice tuple."""

    provider: str
    model_id: str = ""
    voice_id: str = ""
    currency: str = "USD"
    run_count: int = 0
    completed_run_count: int = 0
    total_characters: int = 0
    total_retry_events: int = 0
    success_rate_percent: float = 0.0
    average_file_accuracy_percent: float = 0.0
    average_character_accuracy_percent: float = 0.0
    average_request_accuracy_percent: float = 0.0
    average_duration_accuracy_percent: float = 0.0
    average_cost_accuracy_percent: float = 0.0
    estimate_accuracy_score: float = 0.0
    duration_multiplier: float = 1.0
    cost_multiplier: float = 1.0
    characters_per_minute: float = 0.0
    confidence: str = "low"
    recommendations: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GenerationEstimateActualSummary:
    total_runs: int = 0
    completed_runs: int = 0
    partial_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    project_count: int = 0
    provider_count: int = 0
    estimated_files: int = 0
    actual_files: int = 0
    estimated_characters: int = 0
    actual_characters: int = 0
    estimated_requests: int = 0
    actual_requests: int = 0
    estimated_duration_seconds: float = 0.0
    actual_duration_seconds: float = 0.0
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    average_file_accuracy_percent: float = 0.0
    average_character_accuracy_percent: float = 0.0
    average_request_accuracy_percent: float = 0.0
    average_duration_accuracy_percent: float = 0.0
    average_cost_accuracy_percent: float = 0.0
    average_accuracy_score: float = 0.0
    duration_overrun_count: int = 0
    cost_overrun_count: int = 0
    high_variance_count: int = 0
    total_retry_events: int = 0
