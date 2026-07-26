from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapability:
    voice_count: int = 0
    tts_model_count: int = 0
    account_tier: str | None = None
    character_count: int | None = None
    character_limit: int | None = None

    @property
    def remaining_characters(self) -> int | None:
        if self.character_count is None or self.character_limit is None:
            return None
        return max(self.character_limit - self.character_count, 0)


@dataclass(frozen=True)
class ProviderConnectionResult:
    status: str
    message: str
    capability: ProviderCapability | None = None
    retryable: bool = False
    http_status: int | None = None
    provider_code: str | None = None
    request_id: str | None = None

    @property
    def connected(self) -> bool:
        return self.status == "connected"


@dataclass(frozen=True)
class ProviderErrorInfo:
    code: str
    message: str
    retryable: bool
    http_status: int | None = None
    provider_code: str | None = None
    request_id: str | None = None
    technical_details: str | None = None
