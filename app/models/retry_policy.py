from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class FailureCategory(StrEnum):
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    VALIDATION = "validation"
    FILESYSTEM = "filesystem"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RetryHistoryEntry(BaseModel):
    timestamp: str
    event: str
    attempt: int = Field(default=0, ge=0)
    category: FailureCategory = FailureCategory.UNKNOWN
    error_code: str | None = None
    fingerprint: str | None = None
    retryable: bool = False
    delay_seconds: float = Field(default=0.0, ge=0.0)
    message: str = ""


@dataclass(frozen=True)
class FailureAnalysis:
    category: FailureCategory
    error_code: str
    fingerprint: str
    retryable: bool
    permanent: bool
    message: str


@dataclass(frozen=True)
class RetryDecision:
    eligible: bool
    reason: str
    delay_seconds: float = 0.0
    next_retry_at: str | None = None


@dataclass(frozen=True)
class RetryBatchResult:
    requested: int = 0
    scheduled: int = 0
    blocked: int = 0
    blocked_reasons: dict[str, int] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)
    row_numbers: tuple[int, ...] = ()

    def __int__(self) -> int:
        return self.scheduled

    def __bool__(self) -> bool:
        return self.scheduled > 0
