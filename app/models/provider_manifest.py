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
    forced_file_extension: str | None = None
    profile_metadata_fields: tuple[str, ...] = ()
    profile_management_ready: bool = False
    profile_secret_required: bool = True
    synthesis_request_limit: int | None = None
    synthesis_request_limit_unit: str | None = None
    synthesis_request_limit_note: str = ""
    controls: ProviderControlPolicy = ProviderControlPolicy()

    def __post_init__(self) -> None:
        normalized = self.provider_id.strip().casefold()
        if not normalized or normalized != self.provider_id:
            raise ValueError("provider_id must be a non-empty lowercase stable identifier")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        if self.locality == "local" and self.credential_mode != "none":
            raise ValueError("local providers cannot require cloud credentials")
        normalized_fields = tuple(field.strip().casefold() for field in self.profile_metadata_fields)
        if any(not field for field in normalized_fields):
            raise ValueError("profile metadata field names cannot be blank")
        if len(set(normalized_fields)) != len(normalized_fields):
            raise ValueError("profile metadata field names must be unique")
        if normalized_fields != self.profile_metadata_fields:
            raise ValueError("profile metadata field names must be lowercase stable identifiers")
        if self.forced_file_extension is not None and not self.forced_file_extension.startswith("."):
            raise ValueError("forced_file_extension must start with a dot")
        if self.synthesis_request_limit is not None and self.synthesis_request_limit <= 0:
            raise ValueError("synthesis_request_limit must be positive")
        if self.synthesis_request_limit_unit not in {None, "characters", "bytes", "billed_characters"}:
            raise ValueError("unsupported synthesis_request_limit_unit")
        if self.synthesis_request_limit is None and self.synthesis_request_limit_unit is not None:
            raise ValueError("synthesis_request_limit_unit requires synthesis_request_limit")

    @property
    def remote(self) -> bool:
        return self.locality == "cloud"

    @property
    def requires_credential(self) -> bool:
        return self.credential_mode != "none"

    @property
    def credential_setup_available(self) -> bool:
        return self.credential_mode in {"none", "api_key", "profile", "profile_or_key"}

    def profile_credential_ready(self, *, has_saved_secret: bool) -> bool:
        """Return whether a named profile has the credential material this provider needs.

        Some providers (Google ADC and AWS named/default profiles) resolve credentials
        outside S-Talking's secure credential store.  Cloud providers that use an API
        key or subscription key keep the historical saved-secret requirement.
        """

        if self.credential_mode == "none":
            return True
        return bool(has_saved_secret) if self.profile_secret_required else True
