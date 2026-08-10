from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PiperAccelerationDecision:
    requested: str
    resolved: str
    cuda_available: bool
    detail: str


@dataclass(frozen=True)
class PiperRuntimeHealth:
    available: bool
    model_path: str | None
    loaded: bool
    requested_acceleration: str
    resolved_acceleration: str
    cuda_available: bool
    cache_entries: int
    load_count: int
    synthesis_count: int
    last_error: str | None = None
    fallback_reason: str | None = None
