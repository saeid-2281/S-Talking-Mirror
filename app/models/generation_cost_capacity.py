from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationPricingRate:
    rate_id: str
    project_id: int | None
    provider: str
    model: str = "*"
    price_per_million_characters: float = 0.0
    currency: str = "USD"
    source: str = "manual"
    effective_from: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationCostBudgetPolicy:
    project_id: int | None = None
    enabled: bool = True
    currency: str = "USD"
    daily_budget: float = 0.0
    weekly_budget: float = 0.0
    monthly_budget: float = 0.0
    warning_percent: float = 80.0
    max_queue_cost: float = 0.0
    default_price_per_million_characters: float = 0.0
    bill_retry_characters: bool = True
    alert_cooldown_minutes: int = 240
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationSessionCost:
    session_id: str
    project_id: int | None
    provider: str
    model: str
    currency: str
    character_count: int = 0
    retry_characters: int = 0
    billable_characters: int = 0
    price_per_million_characters: float = 0.0
    estimated_cost: float = 0.0
    actual_cost: float | None = None
    cost_source: str = "estimated"
    recorded_at: str = ""

    @property
    def effective_cost(self) -> float:
        return self.actual_cost if self.actual_cost is not None else self.estimated_cost


@dataclass(frozen=True)
class GenerationProviderCostEfficiency:
    provider: str
    model: str
    session_count: int = 0
    total_jobs: int = 0
    completed_jobs: int = 0
    total_characters: int = 0
    retry_characters: int = 0
    total_cost: float = 0.0
    retry_cost: float = 0.0
    cost_per_file: float = 0.0
    cost_per_million_characters: float = 0.0
    average_files_per_minute: float = 0.0
    average_characters_per_minute: float = 0.0
    success_rate: float = 0.0


@dataclass(frozen=True)
class GenerationCapacityForecast:
    project_id: int | None
    provider: str
    model: str
    currency: str
    queued_jobs: int = 0
    queued_characters: int = 0
    estimated_cost: float = 0.0
    estimated_duration_seconds: float = 0.0
    estimated_completion_at: str | None = None
    files_per_minute: float = 0.0
    characters_per_minute: float = 0.0
    historical_session_count: int = 0
    confidence: str = "low"
    limiting_factor: str = "historical-throughput"


@dataclass(frozen=True)
class GenerationCostCapacitySnapshot:
    snapshot_id: str
    project_id: int | None
    period_start: str
    period_end: str
    created_at: str
    currency: str = "USD"
    session_count: int = 0
    total_characters: int = 0
    retry_characters: int = 0
    total_cost: float = 0.0
    retry_cost: float = 0.0
    daily_spend: float = 0.0
    weekly_spend: float = 0.0
    monthly_spend: float = 0.0
    daily_budget_usage_percent: float = 0.0
    weekly_budget_usage_percent: float = 0.0
    monthly_budget_usage_percent: float = 0.0
    projected_monthly_cost: float = 0.0
    queue_forecast: GenerationCapacityForecast | None = None
    provider_metrics: tuple[GenerationProviderCostEfficiency, ...] = ()
    state: str = "healthy"
    reasons: tuple[str, ...] = ()
    alert_fingerprint: str | None = None
    alert_notification_id: str | None = None


@dataclass(frozen=True)
class GenerationCostCapacityDashboard:
    policy: GenerationCostBudgetPolicy
    snapshot: GenerationCostCapacitySnapshot
    rates: tuple[GenerationPricingRate, ...] = ()
    recent_costs: tuple[GenerationSessionCost, ...] = ()
    history: tuple[GenerationCostCapacitySnapshot, ...] = ()
    budget_status: dict[str, str] = field(default_factory=dict)
