from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.models import AppSettings
from app.models.provider_identity import ProviderReadiness
from app.provider_factory import PROVIDER_CLASSES, available_provider_ids, create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from app.providers.piper_installation import resolve_piper_executable
from app.services.provider_identity_service import ProviderIdentityService


class ProviderReadinessService:
    """Audit whether a provider is safe to expose for production generation."""

    def __init__(
        self,
        identity_service: ProviderIdentityService | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.identity_service = identity_service or ProviderIdentityService()
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY

    def readiness_for(self, provider_id: str, settings: AppSettings | None = None) -> ProviderReadiness:
        manifest = self.registry.manifest_for(provider_id)
        registered = provider_id in PROVIDER_CLASSES
        identity = self.identity_service.identity_for(provider_id)
        dependency = manifest.optional_dependency
        dependency_installed = self._dependency_installed(dependency)
        missing: list[str] = []
        if not registered:
            missing.append("provider adapter is not registered")
        if dependency and not dependency_installed:
            missing.append(f"optional dependency is missing: {dependency}")

        provider = None
        capabilities = None
        validation_ok = False
        validation_message = ""
        if registered:
            try:
                probe_settings = self._probe_settings(provider_id, settings)
                provider = create_provider(probe_settings)
                capabilities = provider.capabilities()
                validation = provider.validate_configuration(probe_settings)
                validation_ok = validation.ok
                validation_message = validation.message
                if validation.missing_dependency and validation.missing_dependency not in missing:
                    missing.append(f"missing dependency: {validation.missing_dependency}")
            except Exception as exc:
                validation_message = str(exc)
                if manifest.setup_kind in {"local_model", "credential"}:
                    missing.append(validation_message)

        list_voices = callable(getattr(provider, "list_voices", None))
        list_models = callable(getattr(provider, "list_models", None))
        synthesize = callable(getattr(provider, "synthesize", None)) or registered
        normalize = callable(getattr(provider, "normalize_error", None)) or registered
        cancellation = (
            callable(getattr(provider, "cancel", None))
            or callable(getattr(provider, "cancel_active_request", None))
            or manifest.production_supported
        )
        formats = tuple(getattr(capabilities, "supported_output_formats", ()) or ())
        output_format_supported = bool(formats or manifest.fallback_output_formats)
        credential_setup = manifest.credential_setup_available
        gui_settings = manifest.production_supported
        preflight = manifest.production_supported
        language = manifest.supports_language_code_fallback or bool(capabilities is not None)

        state = "Ready but unverified live"
        reason = validation_message or "Provider path is registered."
        if not registered:
            state = "Not production-ready"
        elif dependency and not dependency_installed:
            state = "Dependency missing"
        elif manifest.setup_kind == "local_model" and not validation_ok:
            state = "Setup required"
        elif manifest.setup_kind == "credential" and settings and not settings.api_key:
            state = "Setup required"
            missing.append("API key or credential profile is required")
        elif manifest.setup_kind in {"optional_cloud", "optional_local"} and (
            not dependency_installed or not validation_ok
        ):
            state = "Setup required" if dependency_installed else "Dependency missing"
        elif manifest.setup_kind == "test":
            state = "Ready"
            reason = "Local test WAV provider is ready."
        elif not synthesize or not output_format_supported:
            state = "Partial implementation"

        if manifest.setup_kind in {"optional_cloud", "optional_local"} and state == "Ready but unverified live":
            reason = "Optional provider SDK is present, but live account/output verification has not been completed."
        if state == "Ready but unverified live" and not validation_ok and manifest.setup_kind != "credential":
            state = "Setup required"

        return ProviderReadiness(
            provider_id=provider_id,
            display_name=identity.display_name,
            state=state,
            reason=reason,
            adapter_registered=registered,
            dependency_installed=dependency_installed,
            credential_setup_available=credential_setup,
            model_listing_implemented=list_models,
            voice_listing_implemented=list_voices,
            language_handling_implemented=language,
            synthesis_implemented=synthesize,
            output_format_supported=output_format_supported,
            cancellation_implemented=cancellation,
            atomic_output_implemented=True,
            retry_implemented=manifest.retry_ready,
            error_normalization_implemented=normalize,
            preflight_integration_implemented=preflight,
            gui_settings_implemented=gui_settings,
            live_manual_verification_status="verified local" if manifest.verified_locally else "unverified",
            missing_requirements=tuple(dict.fromkeys(item for item in missing if item)),
        )

    def matrix(self, settings: AppSettings | None = None) -> dict[str, dict[str, object]]:
        provider_ids = self.registry.ordered_provider_ids(available_provider_ids())
        return {provider_id: asdict(self.readiness_for(provider_id, settings)) for provider_id in provider_ids}

    def write_matrix(self, artifact_root: Path, settings: AppSettings | None = None) -> Path:
        latest = artifact_root / "provider-readiness" / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "providers": self.matrix(settings),
        }
        path = latest / "readiness.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def _dependency_installed(cls, dependency: str | None) -> bool:
        if not dependency:
            return True
        try:
            installed = importlib.util.find_spec(dependency) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            installed = False
        if dependency == "piper" and not installed:
            return bool(resolve_piper_executable(executable_finder=shutil.which))
        return installed

    def _probe_settings(self, provider_id: str, settings: AppSettings | None) -> AppSettings:
        base = settings.model_copy(update={"provider": provider_id}) if settings else AppSettings(provider=provider_id)
        manifest = self.registry.manifest_for(provider_id)
        if manifest.placeholder_api_key and not base.api_key:
            base.api_key = "readiness-placeholder"
        return base
