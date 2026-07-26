from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProviderIdentity:
    provider_id: str
    display_name: str
    short_name: str
    icon_name: str
    locality: str
    help_url: str
    logo_asset: Path | None = None
    fallback_icon: str = "settings"


@dataclass(frozen=True)
class ProviderReadiness:
    provider_id: str
    display_name: str
    state: str
    reason: str
    adapter_registered: bool
    dependency_installed: bool
    credential_setup_available: bool
    model_listing_implemented: bool
    voice_listing_implemented: bool
    language_handling_implemented: bool
    synthesis_implemented: bool
    output_format_supported: bool
    cancellation_implemented: bool
    atomic_output_implemented: bool
    retry_implemented: bool
    error_normalization_implemented: bool
    preflight_integration_implemented: bool
    gui_settings_implemented: bool
    live_manual_verification_status: str = "unverified"
    missing_requirements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocks_generation(self) -> bool:
        return self.state in {
            "Setup required",
            "Dependency missing",
            "Partial implementation",
            "Not production-ready",
        }
