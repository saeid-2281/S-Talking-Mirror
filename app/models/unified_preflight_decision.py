from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UnifiedPreflightSignal:
    """One normalized input contributing to the final launch decision."""

    source: str
    code: str
    title: str
    detail: str
    severity: str = "info"
    suggested_action: str = ""
    blocking: bool = False
    requires_approval: bool = False


@dataclass(frozen=True)
class UnifiedPreflightDecision:
    """One explainable decision shared by launch UI, receipts, and tests."""

    status: str = "ready"
    allowed: bool = True
    headline: str = "Ready"
    summary: str = "All preflight decision sources are ready."
    trace_id: str = ""
    signals: tuple[UnifiedPreflightSignal, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)
    blocker_count: int = 0
    warning_count: int = 0
    approval_count: int = 0

    @property
    def requires_attention(self) -> bool:
        return self.status in {"ready_with_warnings", "approval_required", "blocked"}

    @property
    def requires_approval(self) -> bool:
        return self.status == "approval_required"
