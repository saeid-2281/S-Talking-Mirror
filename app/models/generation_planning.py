from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationPlanScenario:
    """One deterministic cost/time scenario for the current queue scope."""

    key: str
    label: str
    retry_reserve_percent: int
    files: int
    characters: int
    provider_requests: int
    estimated_cost: float
    estimated_duration_seconds: float


@dataclass(frozen=True)
class BatchGenerationPlan:
    """Decision-ready snapshot shown before a generation run starts."""

    provider: str = ""
    model: str = ""
    files: int = 0
    characters: int = 0
    provider_requests: int = 0
    estimated_cost: float = 0.0
    currency: str = "USD"
    price_per_million_characters: float = 0.0
    pricing_source: str = "unavailable"
    estimated_duration_seconds: float = 0.0
    estimated_completion_at: str | None = None
    throughput_confidence: str = "low"
    limiting_factor: str = "fallback"
    historical_session_count: int = 0
    quota_remaining: int | None = None
    quota_shortfall: int = 0
    quota_usage_percent: float | None = None
    max_queue_cost: float = 0.0
    budget_usage_percent: float | None = None
    risk_level: str = "low"
    reasons: tuple[str, ...] = ()
    scenarios: tuple[GenerationPlanScenario, ...] = field(default_factory=tuple)

    @property
    def cost_available(self) -> bool:
        return self.price_per_million_characters > 0.0 or self.estimated_cost > 0.0

    @property
    def quota_known(self) -> bool:
        return self.quota_remaining is not None
