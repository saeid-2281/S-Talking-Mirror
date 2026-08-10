from __future__ import annotations

from dataclasses import dataclass

from app.models.api_profile import ApiProfile, ApiProfileFailoverMode
from app.models.provider_health import ProviderHealthState, evaluate_provider_health
from app.services.api_profile_service import ApiProfileService
from app.services.provider_catalog_service import ProviderCatalogService


@dataclass(frozen=True)
class ProviderAccountProviderSummary:
    provider_id: str
    display_name: str
    credential_mode: str
    account_count: int
    enabled_count: int
    active_profile_id: str | None
    active_profile_name: str | None
    healthy_count: int
    attention_count: int
    exhausted_count: int
    disabled_count: int
    failover_mode: ApiProfileFailoverMode
    failover_supported: bool
    metadata_fields: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return self.account_count > 0

    @property
    def status_label(self) -> str:
        if self.account_count == 0:
            return "Not configured"
        if self.attention_count:
            return f"{self.attention_count} need attention"
        if self.active_profile_name:
            return f"Active: {self.active_profile_name}"
        return "Configured"


@dataclass(frozen=True)
class ProviderAccountsCenterSummary:
    managed_provider_count: int
    configured_provider_count: int
    account_count: int
    enabled_account_count: int
    active_provider_count: int
    attention_account_count: int
    exhausted_account_count: int


@dataclass(frozen=True)
class ProviderAccountActionPolicy:
    can_replace_secret: bool
    can_use_temporary_secret: bool
    can_edit_metadata: bool
    can_configure_failover: bool
    credential_mode: str


class ProviderAccountsCenterService:
    """Read-only cross-provider inventory and UI policy for named accounts.

    The account service remains authoritative for mutations and secure credential
    storage.  This service only composes provider manifests with profile state so
    the GUI does not need provider-id branches for account-center behavior.
    """

    def __init__(
        self,
        profiles: ApiProfileService,
        catalog: ProviderCatalogService,
    ) -> None:
        self.profiles = profiles
        self.catalog = catalog

    def managed_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            provider_id
            for provider_id in self.catalog.provider_ids()
            if self._managed(provider_id)
        )

    def provider_summaries(self) -> tuple[ProviderAccountProviderSummary, ...]:
        return tuple(self.provider_summary(provider_id) for provider_id in self.managed_provider_ids())

    def provider_summary(self, provider_id: str) -> ProviderAccountProviderSummary:
        manifest = self.catalog.manifest_for(provider_id)
        profiles = self.profiles.list_profiles(provider_id)
        states = [evaluate_provider_health(profile).state for profile in profiles]
        active = next((profile for profile in profiles if profile.active), None)
        attention_states = {
            ProviderHealthState.DEGRADED,
            ProviderHealthState.EXHAUSTED,
            ProviderHealthState.OFFLINE,
            ProviderHealthState.STALE,
        }
        return ProviderAccountProviderSummary(
            provider_id=provider_id,
            display_name=manifest.display_name,
            credential_mode=manifest.credential_mode,
            account_count=len(profiles),
            enabled_count=sum(1 for profile in profiles if profile.enabled),
            active_profile_id=active.profile_id if active else None,
            active_profile_name=active.display_name if active else None,
            healthy_count=sum(1 for state in states if state == ProviderHealthState.HEALTHY),
            attention_count=sum(1 for state in states if state in attention_states),
            exhausted_count=sum(1 for state in states if state == ProviderHealthState.EXHAUSTED),
            disabled_count=sum(1 for state in states if state == ProviderHealthState.DISABLED),
            failover_mode=self.profiles.failover_settings(provider_id).mode,
            failover_supported=manifest.controls.account_failover,
            metadata_fields=manifest.profile_metadata_fields,
        )

    def overview(self) -> ProviderAccountsCenterSummary:
        summaries = self.provider_summaries()
        return ProviderAccountsCenterSummary(
            managed_provider_count=len(summaries),
            configured_provider_count=sum(1 for item in summaries if item.configured),
            account_count=sum(item.account_count for item in summaries),
            enabled_account_count=sum(item.enabled_count for item in summaries),
            active_provider_count=sum(1 for item in summaries if item.active_profile_id),
            attention_account_count=sum(item.attention_count for item in summaries),
            exhausted_account_count=sum(item.exhausted_count for item in summaries),
        )

    def action_policy(self, profile: ApiProfile) -> ProviderAccountActionPolicy:
        manifest = self.catalog.manifest_for(profile.provider)
        secret_managed = manifest.profile_secret_required and manifest.credential_mode in {
            "api_key",
            "profile",
            "profile_or_key",
        }
        return ProviderAccountActionPolicy(
            can_replace_secret=secret_managed,
            can_use_temporary_secret=manifest.controls.api_key and secret_managed,
            can_edit_metadata=bool(manifest.profile_metadata_fields),
            can_configure_failover=manifest.controls.account_failover,
            credential_mode=manifest.credential_mode,
        )

    def profiles_for_view(self, provider_id: str | None, query: str = "") -> list[ApiProfile]:
        managed_ids = self.managed_provider_ids()
        managed = set(managed_ids)
        profiles = self.profiles.list_profiles(provider_id) if provider_id else self.profiles.list_profiles()
        profiles = [profile for profile in profiles if profile.provider in managed]
        if provider_id is None:
            provider_order = {item: index for index, item in enumerate(managed_ids)}
            profiles.sort(
                key=lambda profile: (
                    provider_order.get(profile.provider, len(provider_order)),
                    profile.priority,
                    profile.display_name.casefold(),
                )
            )
        needle = str(query or "").strip().casefold()
        if not needle:
            return profiles
        filtered: list[ApiProfile] = []
        for profile in profiles:
            manifest = self.catalog.manifest_for(profile.provider)
            health = evaluate_provider_health(profile)
            searchable = " ".join(
                (
                    profile.display_name,
                    profile.provider,
                    manifest.display_name,
                    str(profile.status),
                    health.label,
                    profile.account_tier or "",
                )
            ).casefold()
            if needle in searchable:
                filtered.append(profile)
        return filtered

    def safe_inventory_summary(self) -> str:
        lines: list[str] = []
        for summary in self.provider_summaries():
            active = summary.active_profile_name or "none"
            lines.append(
                f"{summary.display_name} [{summary.provider_id}]: "
                f"accounts={summary.account_count} enabled={summary.enabled_count} "
                f"active={active} attention={summary.attention_count} "
                f"failover={summary.failover_mode}"
            )
        provider_summary = "\n".join(lines) or "No managed provider accounts are available."
        account_summary = self.profiles.safe_summary()
        return f"{provider_summary}\n\nAccounts:\n{account_summary}"

    def _managed(self, provider_id: str) -> bool:
        manifest = self.catalog.manifest_for(provider_id)
        return bool(manifest.profile_management_ready and manifest.controls.api_profile)
