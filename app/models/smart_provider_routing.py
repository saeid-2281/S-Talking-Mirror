from __future__ import annotations

from dataclasses import dataclass


ROUTING_PREFERENCES = (
    "balanced",
    "reliability",
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
    score: int = 0
    rank: int = 0
    eligible: bool = True
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    language_state: str = "unknown"
    voice_state: str = "unknown"
    model_state: str = "unknown"
    account_state: str = "unknown"
    request_limit_state: str = "unknown"
    profile_id: str | None = None
    profile_name: str | None = None
    recommended_model_id: str | None = None
    recommended_voice_id: str | None = None

    @property
    def cost_known(self) -> bool:
        return self.estimated_cost is not None

    @property
    def blocked(self) -> bool:
        return not self.ready or not self.eligible or self.quota_shortfall > 0 or bool(self.blockers)

    @property
    def cost_text(self) -> str:
        if self.estimated_cost is None:
            return "Pricing unknown"
        currency = self.currency or ""
        if self.estimated_cost <= 0:
            return "No provider fee" if self.locality == "local" else f"{currency} 0.0000".strip()
        return f"{currency} {self.estimated_cost:.4f}".strip()

    @property
    def evidence_text(self) -> str:
        values = (
            f"language {self.language_state}",
            f"voice {self.voice_state}",
            f"model {self.model_state}",
            f"account {self.account_state}",
            f"limit {self.request_limit_state}",
        )
        return " · ".join(values)


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
    candidates: tuple[ProviderRouteCandidate, ...] = ()
    confidence: str = "medium"
    decision_factors: tuple[str, ...] = ()
    engine_version: int = 2

    @property
    def recommends_piper(self) -> bool:
        return self.recommended_provider_id == "piper" and self.switch_required

    @property
    def recommended_candidate(self) -> ProviderRouteCandidate:
        return next(
            (
                candidate
                for candidate in self.candidates
                if candidate.provider_id == self.recommended_provider_id
            ),
            self.current_candidate,
        )
