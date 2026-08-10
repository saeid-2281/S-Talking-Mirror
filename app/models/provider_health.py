from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.api_profile import ApiProfile, ApiProfileStatus


class ProviderHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    EXHAUSTED = "exhausted"
    STALE = "stale"
    OFFLINE = "offline"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ProviderAccountHealth:
    state: ProviderHealthState
    label: str
    reason: str
    eligible_for_failover: bool
    quota_percent: int | None = None
    latency_ms: int | None = None


def evaluate_provider_health(
    profile: ApiProfile,
    snapshot: object | None = None,
) -> ProviderAccountHealth:
    """Derive a stable operational health state from profile and catalog data."""

    latency = _as_int(profile.metadata.get("last_sync_latency_ms"))
    quota_percent = _quota_percent(profile)

    if not profile.enabled:
        return ProviderAccountHealth(
            ProviderHealthState.DISABLED,
            "Disabled",
            "Account is disabled.",
            False,
            quota_percent,
            latency,
        )
    if not profile.credential_ready or profile.status in {
        ApiProfileStatus.UNAVAILABLE,
        ApiProfileStatus.INVALID,
    }:
        return ProviderAccountHealth(
            ProviderHealthState.OFFLINE,
            "Offline",
            profile.last_error or "Account is unavailable or has no usable credential configuration.",
            False,
            quota_percent,
            latency,
        )
    if profile.status == ApiProfileStatus.EXHAUSTED or profile.remaining_characters == 0:
        return ProviderAccountHealth(
            ProviderHealthState.EXHAUSTED,
            "Exhausted",
            "No remaining provider quota.",
            False,
            0,
            latency,
        )
    if snapshot is not None and bool(getattr(snapshot, "exists", False)) and bool(getattr(snapshot, "stale", False)):
        return ProviderAccountHealth(
            ProviderHealthState.STALE,
            "Stale",
            "Account catalog is older than the configured cache lifetime.",
            True,
            quota_percent,
            latency,
        )
    if profile.status in {ApiProfileStatus.UNCHECKED, ApiProfileStatus.TESTING}:
        return ProviderAccountHealth(
            ProviderHealthState.DEGRADED,
            "Degraded",
            "Account has not completed a recent successful health check.",
            True,
            quota_percent,
            latency,
        )
    if quota_percent is not None and quota_percent <= 10:
        return ProviderAccountHealth(
            ProviderHealthState.DEGRADED,
            "Degraded",
            "Remaining quota is at or below 10%.",
            True,
            quota_percent,
            latency,
        )
    if latency is not None and latency >= 3000:
        return ProviderAccountHealth(
            ProviderHealthState.DEGRADED,
            "Degraded",
            "Last provider sync latency was high.",
            True,
            quota_percent,
            latency,
        )
    return ProviderAccountHealth(
        ProviderHealthState.HEALTHY,
        "Healthy",
        "Account is enabled, reachable and has usable quota.",
        True,
        quota_percent,
        latency,
    )


def _quota_percent(profile: ApiProfile) -> int | None:
    if profile.remaining_characters is None or not profile.character_limit:
        return None
    return max(0, min(100, round((profile.remaining_characters / profile.character_limit) * 100)))


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
