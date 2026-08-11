"""Public Provider Plugin SDK contract for S-Talking.

Phase 111 intentionally keeps provider plugins explicit and session-scoped.
Importing this module does not discover or activate third-party code.
"""

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import (
    ProviderCapabilities,
    ProviderConfigurationResult,
    ProviderNormalizedError,
    ProviderUsageEstimate,
    SynthesisRequest,
)
from app.models.provider_manifest import ProviderControlPolicy, ProviderManifest
from app.models.provider_plugin import PLUGIN_SDK_API_VERSION
from app.providers.base import TTSProvider

__all__ = [
    "PLUGIN_SDK_API_VERSION",
    "AppSettings",
    "ConfigurationError",
    "ProviderCapabilities",
    "ProviderConfigurationResult",
    "ProviderControlPolicy",
    "ProviderError",
    "ProviderManifest",
    "ProviderNormalizedError",
    "ProviderUsageEstimate",
    "SynthesisRequest",
    "TTSProvider",
]
