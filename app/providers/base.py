from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import AppSettings
from app.models.provider_contract import (
    ProviderCapabilities,
    ProviderConfigurationResult,
    ProviderNormalizedError,
    ProviderUsageEstimate,
    SynthesisRequest,
)


class TTSProvider(ABC):
    provider_id = "unknown"
    display_name = "Unknown Provider"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(self.provider_id, self.display_name, remote=False, requires_credential=False)

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        return ProviderConfigurationResult(True, "Configuration is valid.")

    def test_connection(self) -> ProviderConfigurationResult:
        return ProviderConfigurationResult(True, "Provider is available.")

    def list_languages(self) -> list[dict]:
        return []

    def estimate_usage(self, request: SynthesisRequest) -> ProviderUsageEstimate:
        return ProviderUsageEstimate(len(request.text), "characters", reliable=False)

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        return ProviderNormalizedError("provider_error", str(error), retryable=False)

    def cancel_active_request(self) -> None:
        cancel = getattr(self, "cancel", None)
        if callable(cancel):
            cancel()

    @abstractmethod
    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        """Convert text to audio bytes."""

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """Return available voices."""

    @abstractmethod
    def list_models(self) -> list[dict]:
        """Return available models."""
