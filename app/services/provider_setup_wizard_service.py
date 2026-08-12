from __future__ import annotations

from dataclasses import dataclass

from app.models import AppSettings
from app.models.api_profile import ApiProfileStatus
from app.services.api_profile_service import ApiProfileService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_cost_quota_limits_service import ProviderCostQuotaLimitsService
from app.services.unified_voice_model_catalog_service import UnifiedVoiceModelCatalogService


@dataclass(frozen=True)
class ProviderSetupProviderChoice:
    provider_id: str
    display_name: str
    locality: str
    credential_mode: str
    profile_management_ready: bool
    local_model_path_required: bool
    voice_required: bool


@dataclass(frozen=True)
class ProviderSetupAccountChoice:
    profile_id: str
    display_name: str
    status: str
    enabled: bool
    credential_ready: bool
    verified: bool
    remaining_characters: int | None

    @property
    def label(self) -> str:
        parts = [self.display_name]
        if self.verified:
            parts.append("verified")
        elif self.status:
            parts.append(self.status.replace("_", " "))
        if self.remaining_characters is not None:
            parts.append(f"{self.remaining_characters:,} chars")
        return " · ".join(parts)


@dataclass(frozen=True)
class ProviderSetupCatalogChoice:
    item_id: str
    name: str
    kind: str
    languages: tuple[str, ...]
    source_state: str

    @property
    def label(self) -> str:
        return self.name if self.name == self.item_id else f"{self.name} · {self.item_id}"


@dataclass(frozen=True)
class ProviderSetupDraft:
    settings: AppSettings
    provider_name: str
    locality: str
    credential_mode: str
    accounts: tuple[ProviderSetupAccountChoice, ...]
    selected_profile_name: str | None
    catalog_state: str
    catalog_message: str
    voices: tuple[ProviderSetupCatalogChoice, ...]
    models: tuple[ProviderSetupCatalogChoice, ...]
    cost_text: str
    quota_text: str
    request_limit_text: str
    capability_text: str
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def can_apply(self) -> bool:
        return not self.blockers


class ProviderSetupWizardService:
    """User-controlled provider setup composition for Roadmap 2 A3.

    Reading choices and cached metadata is side-effect free. The service never
    changes the active provider/account, runs Preflight, starts generation, or
    refreshes/probes a provider unless :meth:`refresh_provider_explicit` is
    called by an explicit UI action.
    """

    def __init__(
        self,
        profiles: ApiProfileService,
        providers: ProviderCatalogService,
        catalog: UnifiedVoiceModelCatalogService,
        cost_quota_limits: ProviderCostQuotaLimitsService,
    ) -> None:
        self.profiles = profiles
        self.providers = providers
        self.catalog = catalog
        self.cost_quota_limits = cost_quota_limits

    @staticmethod
    def safety_contract() -> dict[str, bool]:
        return {
            "automatic_provider_switch": False,
            "automatic_account_change": False,
            "automatic_catalog_refresh": False,
            "automatic_provider_probe": False,
            "automatic_preflight_run": False,
            "automatic_generation_start": False,
            "automatic_generation_restart": False,
            "automatic_cross_provider_failover": False,
            "explicit_apply_required": True,
            "explicit_refresh_required": True,
        }

    def provider_choices(self) -> tuple[ProviderSetupProviderChoice, ...]:
        choices: list[ProviderSetupProviderChoice] = []
        for provider_id in self.providers.provider_ids():
            manifest = self.providers.manifest_for(provider_id)
            choices.append(
                ProviderSetupProviderChoice(
                    provider_id=provider_id,
                    display_name=manifest.display_name,
                    locality=manifest.locality,
                    credential_mode=manifest.credential_mode,
                    profile_management_ready=manifest.profile_management_ready,
                    local_model_path_required=manifest.controls.local_model_path,
                    voice_required=manifest.controls.voice_required,
                )
            )
        return tuple(choices)

    def default_profile_id(self, base_settings: AppSettings, provider_id: str) -> str | None:
        provider_id = self._provider_id(provider_id)
        if provider_id != str(base_settings.provider or "").strip().casefold():
            return None
        profile_id = str(base_settings.active_api_profile_id or "").strip()
        if not profile_id:
            return None
        try:
            profile = self.profiles.get_profile(profile_id)
        except ValueError:
            return None
        return profile_id if profile.provider == provider_id else None

    def build_draft(
        self,
        base_settings: AppSettings,
        *,
        provider_id: str,
        profile_id: str | None,
        voice_id: str | None = None,
        model_id: str | None = None,
        language_code: str | None = None,
        project_id: int | None = None,
        scoped_characters: int = 0,
    ) -> ProviderSetupDraft:
        provider_id = self._provider_id(provider_id)
        manifest = self.providers.manifest_for(provider_id)
        settings, selected_profile_name = self._settings_for_choice(
            base_settings,
            provider_id=provider_id,
            profile_id=profile_id,
        )

        current_provider = str(base_settings.provider or "").strip().casefold()
        selected_voice = (
            str(voice_id).strip()
            if voice_id is not None
            else str(base_settings.voice_id or "").strip()
            if provider_id == current_provider
            else ""
        )
        selected_model = (
            str(model_id).strip()
            if model_id is not None
            else str(base_settings.model_id or "").strip()
            if provider_id == current_provider
            else ""
        )
        selected_language = (
            language_code
            if language_code is not None
            else base_settings.language_code
        )
        settings = settings.model_copy(
            update={
                "voice_id": selected_voice,
                "model_id": selected_model,
                "language_code": selected_language,
            }
        )

        catalog = self.catalog.snapshot_explicit_settings(
            provider_id,
            settings,
            allow_stale=True,
        )
        source = catalog.sources[0]
        voices = tuple(
            ProviderSetupCatalogChoice(
                item_id=item.item_id,
                name=item.name,
                kind=item.kind,
                languages=item.languages,
                source_state=item.source_state,
            )
            for item in catalog.items
            if item.provider_id == provider_id and item.kind == "voice"
        )
        models = tuple(
            ProviderSetupCatalogChoice(
                item_id=item.item_id,
                name=item.name,
                kind=item.kind,
                languages=item.languages,
                source_state=item.source_state,
            )
            for item in catalog.items
            if item.provider_id == provider_id and item.kind == "model"
        )

        accounts = self._accounts(provider_id)
        if manifest.requires_credential and profile_id is None:
            cost_text = "Choose a named account to resolve account-scoped cost context."
            quota_text = "Choose a named account to resolve cached quota context."
            if manifest.synthesis_request_limit is not None:
                unit = manifest.synthesis_request_limit_unit or "units"
                request_limit_text = (
                    f"{manifest.synthesis_request_limit:,} {unit} per request · provider contract"
                )
            else:
                request_limit_text = manifest.synthesis_request_limit_note or "Request limit is not confirmed yet."
        else:
            row = self.cost_quota_limits.provider_row(
                provider_id,
                settings,
                project_id=project_id,
                scoped_characters=max(0, int(scoped_characters)),
            )
            cost_text = self._cost_text(row)
            quota_text = self._quota_text(row)
            request_limit_text = self._limit_text(row)
        capability_parts = ["Text-to-Speech"]
        capability_parts.append("voice required" if manifest.controls.voice_required else "voice optional")
        if getattr(manifest, "supports_language_code_fallback", False):
            capability_parts.append("language code supported")
        output_formats = tuple(getattr(manifest, "fallback_output_formats", ()) or ())
        if output_formats:
            capability_parts.append("outputs: " + "/".join(output_formats))
        if manifest.controls.local_model_path:
            capability_parts.append("local model path required")
        capability_text = " · ".join(capability_parts)

        warnings: list[str] = []
        blockers: list[str] = []

        selected_profile = next(
            (item for item in accounts if item.profile_id == profile_id),
            None,
        )
        if selected_profile is not None:
            if not selected_profile.enabled:
                blockers.append("The selected provider account is disabled.")
            if not selected_profile.credential_ready:
                blockers.append("The selected provider account does not have usable credential configuration.")
            if not selected_profile.verified:
                warnings.append("The selected account has not been verified successfully yet. Use the explicit verify/refresh action before Preflight if needed.")
        elif manifest.requires_credential:
            has_temporary_key = bool(settings.api_key)
            if manifest.profile_secret_required and not has_temporary_key:
                blockers.append("Choose a credential-ready provider account before applying this setup.")
            elif not has_temporary_key:
                warnings.append("No named account is selected; this provider may rely on external/default credentials.")
            else:
                warnings.append("A temporary credential is selected. It is not saved as a named provider account.")

        if manifest.controls.local_model_path and not settings.piper_model_path:
            blockers.append("Configure the required local model path in Offline TTS Engines before applying this provider.")
        if manifest.controls.voice_required and not settings.voice_id:
            blockers.append("Choose or enter a voice before applying this setup.")
        if not settings.model_id:
            blockers.append("Choose or enter a model before applying this setup.")
        if source.state in {"not_refreshed", "account_required"}:
            warnings.append(source.message or "Provider catalog has not been refreshed yet.")
        if source.state == "error":
            warnings.append(source.message or "The cached provider catalog reports an error.")

        return ProviderSetupDraft(
            settings=settings,
            provider_name=manifest.display_name,
            locality=manifest.locality,
            credential_mode=manifest.credential_mode,
            accounts=accounts,
            selected_profile_name=selected_profile_name,
            catalog_state=source.state,
            catalog_message=source.message,
            voices=voices,
            models=models,
            cost_text=cost_text,
            quota_text=quota_text,
            request_limit_text=request_limit_text,
            capability_text=capability_text,
            warnings=tuple(dict.fromkeys(warnings)),
            blockers=tuple(dict.fromkeys(blockers)),
        )

    def refresh_provider_explicit(
        self,
        base_settings: AppSettings,
        *,
        provider_id: str,
        profile_id: str | None,
    ):
        """Explicitly contact one provider and refresh only its catalog metadata."""
        provider_id = self._provider_id(provider_id)
        settings, _profile_name = self._settings_for_choice(
            base_settings,
            provider_id=provider_id,
            profile_id=profile_id,
        )
        return self.catalog.refresh_provider_explicit_settings(provider_id, settings)

    def final_settings(
        self,
        base_settings: AppSettings,
        *,
        provider_id: str,
        profile_id: str | None,
        voice_id: str,
        model_id: str,
        language_code: str | None,
    ) -> AppSettings:
        provider_id = self._provider_id(provider_id)
        manifest = self.providers.manifest_for(provider_id)
        settings, _profile_name = self._settings_for_choice(
            base_settings,
            provider_id=provider_id,
            profile_id=profile_id,
        )
        settings = settings.model_copy(
            update={
                "voice_id": str(voice_id or "").strip(),
                "model_id": str(model_id or "").strip(),
                "language_code": str(language_code).strip() if language_code else None,
            }
        )
        if manifest.profile_secret_required and manifest.requires_credential and not settings.api_key:
            raise ValueError("A credential-ready provider account is required before applying this setup.")
        if manifest.controls.local_model_path and not settings.piper_model_path:
            raise ValueError("Configure the local model path before applying this provider.")
        if manifest.controls.voice_required and not settings.voice_id:
            raise ValueError("A voice is required before applying this provider.")
        if not settings.model_id:
            raise ValueError("A model is required before applying this provider.")
        return settings

    def _settings_for_choice(
        self,
        base_settings: AppSettings,
        *,
        provider_id: str,
        profile_id: str | None,
    ) -> tuple[AppSettings, str | None]:
        current_provider = str(base_settings.provider or "").strip().casefold()
        if provider_id == current_provider:
            settings = base_settings.model_copy(update={"provider": provider_id})
        else:
            settings = base_settings.model_copy(
                update={
                    "provider": provider_id,
                    "api_key": "",
                    "active_api_profile_id": None,
                    "provider_options": {},
                    "voice_id": "",
                    "model_id": "",
                }
            )
        profile_id = str(profile_id or "").strip() or None
        if profile_id is None:
            return settings.model_copy(update={"active_api_profile_id": None}), None
        profile = self.profiles.get_profile(profile_id)
        if profile.provider != provider_id:
            raise ValueError(
                f"Provider account {profile.display_name!r} belongs to {profile.provider}, not {provider_id}."
            )
        settings = settings.model_copy(update={"active_api_profile_id": profile_id})
        return self.profiles.apply_profile(settings, profile_id), profile.display_name

    def _accounts(self, provider_id: str) -> tuple[ProviderSetupAccountChoice, ...]:
        manifest = self.providers.manifest_for(provider_id)
        accounts: list[ProviderSetupAccountChoice] = []
        for profile in self.profiles.list_profiles(provider_id):
            credential_ready = manifest.profile_credential_ready(
                has_saved_secret=profile.has_saved_key
            )
            accounts.append(
                ProviderSetupAccountChoice(
                    profile_id=profile.profile_id,
                    display_name=profile.display_name,
                    status=str(profile.status),
                    enabled=profile.enabled,
                    credential_ready=credential_ready,
                    verified=profile.status == ApiProfileStatus.READY,
                    remaining_characters=profile.remaining_characters,
                )
            )
        return tuple(accounts)

    def _provider_id(self, provider_id: str) -> str:
        normalized = str(provider_id or "").strip().casefold()
        if normalized not in self.providers.provider_ids():
            raise ValueError(f"Unknown provider: {provider_id}")
        return normalized

    @staticmethod
    def _cost_text(row) -> str:
        if row.cost.estimated_cost is None:
            return row.cost.message
        currency = f" {row.cost.currency}" if row.cost.currency else ""
        return f"Estimated provider cost: {row.cost.estimated_cost:.4f}{currency} · {row.cost.source}"

    @staticmethod
    def _quota_text(row) -> str:
        if row.quota.remaining is None:
            return row.quota.message
        return f"{row.quota.remaining:,} characters remaining · {row.quota.message}"

    @staticmethod
    def _limit_text(row) -> str:
        if row.request_limit.value is None:
            return row.request_limit.message
        return f"{row.request_limit.value:,} {row.request_limit.unit} per request · {row.request_limit.message}"
