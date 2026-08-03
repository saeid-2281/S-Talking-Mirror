from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationBudgetGuardApproval:
    """Time-bound approval for one exact budget decision fingerprint."""

    approval_id: str
    project_name: str
    decision_fingerprint: str
    reason: str = ""
    approved_by: str = ""
    created_at: str = ""
    expires_at: str = ""
    max_uses: int = 1
    used_count: int = 0
    status: str = "approved"
    revoked_at: str = ""

    @property
    def active(self) -> bool:
        return self.status == "approved" and self.used_count < self.max_uses


@dataclass(frozen=True)
class GenerationBudgetReservation:
    """One secret-free cost and quota reservation tied to an exact run."""

    reservation_id: str
    project_id: int | None
    project_name: str
    run_id: str
    launch_fingerprint: str
    provider: str
    model_id: str
    currency: str
    estimated_cost: float = 0.0
    reserved_characters: int = 0
    created_at: str = ""
    expires_at: str = ""
    status: str = "active"
    receipt_id: str = ""
    execution_receipt_id: str = ""
    actual_cost: float | None = None
    released_at: str = ""
    release_reason: str = ""

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def effective_cost(self) -> float:
        return self.actual_cost if self.actual_cost is not None else self.estimated_cost


@dataclass(frozen=True)
class GenerationBudgetGuardDecision:
    """Explainable pre-launch budget and provider-quota decision."""

    status: str
    allowed: bool
    summary: str
    fingerprint: str
    project_id: int | None = None
    project_name: str = ""
    provider: str = ""
    model_id: str = ""
    currency: str = "USD"
    estimated_cost: float = 0.0
    active_reserved_cost: float = 0.0
    projected_daily_spend: float = 0.0
    projected_weekly_spend: float = 0.0
    projected_monthly_spend: float = 0.0
    daily_budget: float = 0.0
    weekly_budget: float = 0.0
    monthly_budget: float = 0.0
    max_queue_cost: float = 0.0
    warning_percent: float = 80.0
    required_characters: int = 0
    active_reserved_characters: int = 0
    quota_remaining: int | None = None
    quota_shortfall: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)
    hard_limit_codes: tuple[str, ...] = field(default_factory=tuple)
    warning_codes: tuple[str, ...] = field(default_factory=tuple)
    approval_id: str = ""
    requires_acknowledgement: bool = False
    reservation_id: str = ""

    @property
    def blocked(self) -> bool:
        return not self.allowed

    @property
    def approval_applied(self) -> bool:
        return bool(self.approval_id)


@dataclass(frozen=True)
class GenerationBudgetGuardSummary:
    total_reservations: int = 0
    active_reservations: int = 0
    settled_reservations: int = 0
    released_reservations: int = 0
    total_approvals: int = 0
    active_approvals: int = 0
    reserved_cost: float = 0.0
    reserved_characters: int = 0
    currency: str = "USD"


@dataclass(frozen=True)
class GenerationBudgetGuardExport:
    json_path: Path
    csv_path: Path
