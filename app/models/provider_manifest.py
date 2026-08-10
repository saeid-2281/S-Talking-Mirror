from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderLocality = Literal["local", "cloud"]
ProviderCredentialMode = Literal["none", "api_key", "profile", "profile_or_key"]
ProviderSetupKind = Literal["test", "credential", "optional_cloud", "local_model", "optional_local"]


@dataclass(frozen=True)
class ProviderControlPolicy:
    """Provider-specific UI intent kept outside MainWindow branching."""

    api_profile: bool = False
    api_key: bool = False
    account_failover: bool = False
    local_model_path: bool = False
    stability: bool = False
    similarity: bool = False
    style: bool = False
    speaker_boost: bool = False
    voice_browser_fallback: bool = False
    model_listing_fallback: bool = False
    connection_test: bool = True
    voice_required: bool = True


@dataclass(frozen=True)
class ProviderManifest:
    """Stable provider metadata independent of SDK/runtime availability.

    Runtime adapters remain authoritative for live capabilities.  The manifest
    supplies the static information needed to render and audit a provider even
    when its optional SDK or credential is unavailable.
    """

    provider_id: str
    display_name: str
    locality: ProviderLocality
    credential_mode: ProviderCredentialMode
    setup_kind: ProviderSetupKind
    optional_dependency: str | None = None
    production_supported: bool = True
    retry_ready: bool = False
    verified_locally: bool = False
    placeholder_api_key: bool = False
    supports_language_code_fallback: bool = True
    fallback_output_formats: tuple[str, ...] = ("mp3", "wav")
    controls: ProviderControlPolicy = ProviderControlPolicy()

    def __post_init__(self) -> None:
        normalized = self.provider_id.strip().casefold()
        if not normalized or normalized != self.provider_id:
            raise ValueError("provider_id must be a non-empty lowercase stable identifier")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        if self.locality == "local" and self.credential_mode != "none":
            raise ValueError("local providers cannot require cloud credentials")

    @property
    def remote(self) -> bool:
        return self.locality == "cloud"

    @property
    def requires_credential(self) -> bool:
        return self.credential_mode != "none"

    @property
    def credential_setup_available(self) -> bool:
        return self.credential_mode in {"none", "api_key", "profile", "profile_or_key"}
