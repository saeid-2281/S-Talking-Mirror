from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


InsightState = Literal["known", "unknown", "not_applicable", "warning", "blocked"]


@dataclass(frozen=True)
class ProviderCostInsight:
    state: InsightState
    estimated_cost: float | None
    rate_per_million_characters: float | None
    currency: str | None
    source: str
    message: str

    @property
    def known(self) -> bool:
        return self.estimated_cost is not None


@dataclass(frozen=True)
class ProviderQuotaInsight:
    state: InsightState
    remaining: int | None
    limit: int | None
    used: int | None
    usage_percent: float | None
    batch_percent_of_remaining: float | None
    shortfall: int
    source: str
    message: str

    @property
    def known(self) -> bool:
        return self.remaining is not None


@dataclass(frozen=True)
class ProviderRequestLimitInsight:
    state: InsightState
    value: int | None
    unit: str
    source: str
    message: str

    @property
    def known(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class ProviderCostQuotaLimitRow:
    provider_id: str
    provider_name: str
    locality: str
    profile_id: str | None
    profile_name: str | None
    model_id: str
    scoped_characters: int
    cost: ProviderCostInsight
    quota: ProviderQuotaInsight
    request_limit: ProviderRequestLimitInsight
    state: InsightState
    summary: str

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.provider_id,
                self.provider_name,
                self.locality,
                self.profile_name or "",
                self.model_id,
                self.cost.source,
                self.cost.message,
                self.quota.source,
                self.quota.message,
                self.request_limit.source,
                self.request_limit.message,
                self.state,
                self.summary,
            )
        ).casefold()


@dataclass(frozen=True)
class ProviderCostQuotaLimitsSnapshot:
    rows: tuple[ProviderCostQuotaLimitRow, ...]
    scoped_characters: int
    generated_at: str

    @property
    def provider_count(self) -> int:
        return len(self.rows)

    @property
    def configured_cost_count(self) -> int:
        return sum(1 for row in self.rows if row.cost.known)

    @property
    def confirmed_quota_count(self) -> int:
        return sum(1 for row in self.rows if row.quota.known)

    @property
    def known_limit_count(self) -> int:
        return sum(1 for row in self.rows if row.request_limit.known)

    @property
    def attention_count(self) -> int:
        return sum(1 for row in self.rows if row.state in {"warning", "blocked"})
