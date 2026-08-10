from __future__ import annotations

from dataclasses import dataclass


ROUTING_PREFERENCES = (
    "balanced",
    "privacy",
    "lowest_cost",
    "cloud_first",
)


@dataclass(frozen=True)
class ProviderRouteCandidate:
    provider_id: str
    provider_name: str
    locality: str
    ready: bool
    status: str
    detail: str
    quota_remaining: int | None = None
    quota_shortfall: int = 0
    estimated_cost: float | None = None
    currency: str | None = None
    cost_source: str | None = None
    selected_voice_id: str | None = None
    selected_model_path: str | None = None

    @property
    def cost_known(self) -> bool:
        return self.estimated_cost is not None

    @property
    def blocked(self) -> bool:
        return not self.ready or self.quota_shortfall > 0

    @property
    def cost_text(self) -> str:
        if self.estimated_cost is None:
            return "Pricing unknown"
        currency = self.currency or ""
        if self.estimated_cost <= 0:
            return "No provider fee" if self.locality == "local" else f"{currency} 0.0000".strip()
        return f"{currency} {self.estimated_cost:.4f}".strip()


@dataclass(frozen=True)
class SmartProviderRoutingState:
    preference: str
    current_provider_id: str
    current_provider_name: str
    recommended_provider_id: str
    recommended_provider_name: str
    route_summary: str
    recommendation: str
    tone: str
    switch_required: bool
    action_label: str
    action_enabled: bool
    current_candidate: ProviderRouteCandidate
    piper_candidate: ProviderRouteCandidate
    scoped_jobs: int
    scoped_characters: int
    no_automatic_failover: bool = True

    @property
    def recommends_piper(self) -> bool:
        return self.recommended_provider_id == "piper" and self.switch_required
