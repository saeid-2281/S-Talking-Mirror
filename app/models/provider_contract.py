from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.domain import AppSettings


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    display_name: str
    remote: bool
    requires_credential: bool
    supports_voice_listing: bool = False
    supports_model_listing: bool = False
    supports_language_code: bool = False
    supports_ssml: bool = False
    supports_pronunciation_dictionary: bool = False
    supports_styles: bool = False
    supports_speed: bool = False
    supports_pitch: bool = False
    supports_volume: bool = False
    supports_streaming: bool = False
    supports_quota_lookup: bool = False
    supports_reliable_cost_estimate: bool = False
    supports_cancellation: bool = False
    supported_output_formats: tuple[str, ...] = ()
    credential_fields: tuple[str, ...] = ()
    optional_dependency: str | None = None


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    settings: AppSettings
    output_path: Path | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderUsageEstimate:
    amount: float | None
    unit: str = "characters"
    reliable: bool = False
    message: str = "Usage estimate unavailable."


@dataclass(frozen=True)
class ProviderConfigurationResult:
    ok: bool
    message: str
    missing_dependency: str | None = None


@dataclass(frozen=True)
class ProviderNormalizedError:
    code: str
    message: str
    retryable: bool = False
    request_id: str | None = None
    safe_details: str = ""
