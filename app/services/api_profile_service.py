from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.models.api_profile import ApiProfile, ApiProfileFailoverMode, ApiProfileStatus, FailoverSettings, ProfileSwitchDecision
from app.models.provider_health import evaluate_provider_health
from app.services.secure_credentials import SecureCredentialStore


class ApiProfileService:
    """Manages named provider accounts without storing raw keys in projects."""

    def __init__(self, metadata_path: Path, credentials: SecureCredentialStore) -> None:
        self.metadata_path = metadata_path
        self.credentials = credentials
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

    def list_profiles(self, provider: str | None = None) -> list[ApiProfile]:
        profiles = [self._profile_from_dict(item) for item in self._read().get("profiles", [])]
        if provider:
            profiles = [profile for profile in profiles if profile.provider == provider]
        return sorted(profiles, key=lambda profile: (profile.priority, profile.display_name.casefold()))

    def create_profile(
        self,
        display_name: str,
        *,
        provider: str = "elevenlabs",
        api_key: str | None = None,
        enabled: bool = True,
        priority: int = 100,
        active: bool = False,
    ) -> ApiProfile:
        name = self._unique_name(display_name.strip() or "Provider profile", provider)
        profile = ApiProfile(
            profile_id=uuid.uuid4().hex,
            display_name=name,
            provider=provider,
            enabled=enabled,
            priority=priority,
            active=active,
            has_saved_key=bool(api_key),
        )
        profiles = self.list_profiles()
        if active:
            for existing in profiles:
                if existing.provider == provider:
                    existing.active = False
        profiles.append(profile)
        if api_key:
            self.credentials.set_password(profile.profile_id, api_key)
        self._write_profiles(profiles)
        return profile

    def update_profile(self, profile: ApiProfile, *, api_key: str | None = None) -> ApiProfile:
        profiles = self.list_profiles()
        self._assert_unique_name(profile.display_name, profile.provider, exclude_id=profile.profile_id, profiles=profiles)
        for index, existing in enumerate(profiles):
            if existing.profile_id == profile.profile_id:
                profile.has_saved_key = existing.has_saved_key if api_key is None else bool(api_key)
                profiles[index] = profile
                break
        else:
            profiles.append(profile)
        if profile.active:
            for existing in profiles:
                if existing.provider == profile.provider and existing.profile_id != profile.profile_id:
                    existing.active = False
        if api_key is not None:
            if api_key:
                self.credentials.set_password(profile.profile_id, api_key)
            else:
                self.credentials.delete_password(profile.profile_id)
        self._write_profiles(profiles)
        return profile

    def rename_profile(self, profile_id: str, display_name: str) -> ApiProfile:
        profile = self.get_profile(profile_id)
        profile.display_name = display_name.strip() or profile.display_name
        return self.update_profile(profile)

    def replace_key(self, profile_id: str, api_key: str) -> ApiProfile:
        profile = self.get_profile(profile_id)
        return self.update_profile(profile, api_key=api_key)

    def set_enabled(self, profile_id: str, enabled: bool) -> ApiProfile:
        profile = self.get_profile(profile_id)
        profile.enabled = enabled
        if not enabled:
            profile.status = ApiProfileStatus.DISABLED
        elif profile.status == ApiProfileStatus.DISABLED:
            profile.status = ApiProfileStatus.UNCHECKED
        return self.update_profile(profile)

    def set_active(self, profile_id: str) -> ApiProfile:
        profile = self.get_profile(profile_id)
        profile.active = True
        return self.update_profile(profile)

    def move_profile(self, profile_id: str, direction: int) -> list[ApiProfile]:
        profiles = self.list_profiles()
        index = next((idx for idx, profile in enumerate(profiles) if profile.profile_id == profile_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(profiles):
            return profiles
        profiles[index], profiles[target] = profiles[target], profiles[index]
        for priority, profile in enumerate(profiles, 1):
            profile.priority = priority
        self._write_profiles(profiles)
        return self.list_profiles()

    def clear_exhausted_state(self, profile_id: str) -> ApiProfile:
        profile = self.get_profile(profile_id)
        if profile.status == ApiProfileStatus.EXHAUSTED:
            profile.status = ApiProfileStatus.UNCHECKED
            profile.remaining_characters = None
            profile.last_error = None
        return self.update_profile(profile)

    def mark_used(self, profile_id: str) -> None:
        profile = self.get_profile(profile_id)
        from datetime import datetime, timezone

        profile.last_used_at = datetime.now(timezone.utc).isoformat()
        self.update_profile(profile)

    def get_profile(self, profile_id: str) -> ApiProfile:
        for profile in self.list_profiles():
            if profile.profile_id == profile_id:
                return profile
        raise ValueError(f"API profile not found: {profile_id}")

    def remove_profile(self, profile_id: str) -> None:
        self.credentials.delete_password(profile_id)
        self._write_profiles([profile for profile in self.list_profiles() if profile.profile_id != profile_id])

    def api_key_for(self, profile_id: str) -> str | None:
        return self.credentials.get_password(profile_id)

    def active_profile(self, provider: str) -> ApiProfile | None:
        profiles = self.list_profiles(provider)
        return next((profile for profile in profiles if profile.active), profiles[0] if profiles else None)

    def failover_settings(self, provider: str = "elevenlabs") -> FailoverSettings:
        raw = self._read().get("failover", {}).get(provider, {})
        try:
            mode = ApiProfileFailoverMode(str(raw.get("mode") or "never"))
        except ValueError:
            mode = ApiProfileFailoverMode.NEVER
        return FailoverSettings(
            mode=mode,
            max_switches_per_run=max(0, int(raw.get("max_switches_per_run", 1))),
            sequence_mode=str(raw.get("sequence_mode") or "active_then_backups"),
            manual_sequence=[str(value) for value in raw.get("manual_sequence", []) if value],
            allow_unknown_quota_override=bool(raw.get("allow_unknown_quota_override", False)),
        )

    def save_failover_settings(self, provider: str, settings: FailoverSettings) -> None:
        data = self._read()
        failover = data.setdefault("failover", {})
        failover[provider] = {
            "mode": str(settings.mode),
            "max_switches_per_run": settings.max_switches_per_run,
            "sequence_mode": settings.sequence_mode,
            "manual_sequence": settings.manual_sequence,
            "allow_unknown_quota_override": settings.allow_unknown_quota_override,
        }
        self._write(data)

    def failover_preview(
        self,
        *,
        provider: str,
        current_profile_id: str | None,
        trigger_reason: str = "insufficient_quota",
    ) -> dict[str, object]:
        profiles = self.list_profiles(provider)
        current = next((profile for profile in profiles if profile.profile_id == current_profile_id), None)
        decision = self.choose_failover(
            provider=provider,
            current_profile_id=current_profile_id,
            mode=str(self.failover_settings(provider).mode),
            error_code=trigger_reason,
        )
        excluded = []
        for profile in profiles:
            if profile.profile_id == current_profile_id:
                excluded.append({"profile": profile.display_name, "reason": "current account"})
            elif not profile.enabled:
                excluded.append({"profile": profile.display_name, "reason": "disabled"})
            elif not profile.has_saved_key:
                excluded.append({"profile": profile.display_name, "reason": "no saved key"})
            elif profile.status == ApiProfileStatus.EXHAUSTED:
                excluded.append({"profile": profile.display_name, "reason": "exhausted"})
        target = self.get_profile(decision.target_profile_id) if decision.target_profile_id else None
        return {
            "current_account": current.display_name if current else "None",
            "next_eligible_account": target.display_name if target else "None",
            "reason": decision.reason,
            "would_switch": decision.should_switch,
            "excluded": excluded,
        }

    def safe_summary(self, provider: str | None = None) -> str:
        lines = []
        for profile in self.list_profiles(provider):
            quota = f"{profile.remaining_characters:,}" if profile.remaining_characters is not None else "unknown"
            lines.append(
                f"{'* ' if profile.active else '- '}{profile.display_name} [{profile.provider}] "
                f"enabled={profile.enabled} status={profile.status} quota={quota} key={profile.masked_key}"
            )
        return "\n".join(lines) or "No provider profiles configured."

    def apply_profile_key(self, settings: Any, profile_id: str | None) -> Any:
        if not profile_id:
            return settings
        secret = self.api_key_for(profile_id)
        if not secret:
            return settings
        return settings.model_copy(update={"api_key": secret, "active_api_profile_id": profile_id})

    def choose_failover(
        self,
        *,
        provider: str,
        current_profile_id: str | None,
        mode: str,
        error_code: str | None,
        generation_active: bool = False,
    ) -> ProfileSwitchDecision:
        normalized = self._failover_mode(mode)
        if normalized == ApiProfileFailoverMode.NEVER:
            return ProfileSwitchDecision(False, reason="failover disabled")
        if generation_active:
            return ProfileSwitchDecision(False, reason="generation is active; account switch deferred")
        if not self._eligible_error(error_code):
            return ProfileSwitchDecision(False, reason="error not eligible for account failover")

        for profile in self.ordered_failover_profiles(provider):
            if profile.profile_id == current_profile_id:
                continue
            health = evaluate_provider_health(profile)
            if not profile.is_usable or not health.eligible_for_failover:
                continue
            return ProfileSwitchDecision(
                normalized == ApiProfileFailoverMode.AUTO,
                profile.profile_id,
                f"{health.label.lower()} profile available after {error_code or 'provider error'}",
            )
        return ProfileSwitchDecision(False, reason="no healthy backup profile")

    def ordered_failover_profiles(self, provider: str) -> list[ApiProfile]:
        profiles = self.list_profiles(provider)
        settings = self.failover_settings(provider)
        if settings.sequence_mode != "manual" or not settings.manual_sequence:
            return profiles
        by_id = {profile.profile_id: profile for profile in profiles}
        ordered = [by_id[profile_id] for profile_id in settings.manual_sequence if profile_id in by_id]
        ordered_ids = {profile.profile_id for profile in ordered}
        ordered.extend(profile for profile in profiles if profile.profile_id not in ordered_ids)
        return ordered

    def activate_failover_target(
        self,
        *,
        provider: str,
        current_profile_id: str | None,
        mode: str,
        error_code: str | None,
        generation_active: bool = False,
    ) -> ProfileSwitchDecision:
        decision = self.choose_failover(
            provider=provider,
            current_profile_id=current_profile_id,
            mode=mode,
            error_code=error_code,
            generation_active=generation_active,
        )
        if decision.should_switch and decision.target_profile_id:
            self.set_active(decision.target_profile_id)
        return decision

    def _read(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {"schema_version": 1, "profiles": []}
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"schema_version": 1, "profiles": []}
        if not isinstance(data, dict):
            return {"schema_version": 1, "profiles": []}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self.metadata_path.with_suffix(self.metadata_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.metadata_path)

    def _write_profiles(self, profiles: list[ApiProfile]) -> None:
        payload = self._read()
        payload["schema_version"] = 1
        payload["profiles"] = [self._profile_to_dict(profile) for profile in profiles]
        self._write(payload)

    @staticmethod
    def _profile_to_dict(profile: ApiProfile) -> dict[str, Any]:
        data = asdict(profile)
        data["status"] = str(profile.status)
        data.pop("metadata", None)
        data["metadata"] = dict(profile.metadata)
        return data

    @staticmethod
    def _profile_from_dict(data: dict[str, Any]) -> ApiProfile:
        status = str(data.get("status") or ApiProfileStatus.UNCHECKED)
        try:
            parsed_status = ApiProfileStatus(status)
        except ValueError:
            parsed_status = ApiProfileStatus.UNCHECKED
        return ApiProfile(
            profile_id=str(data.get("profile_id") or uuid.uuid4().hex),
            display_name=str(data.get("display_name") or "Provider profile"),
            provider=str(data.get("provider") or "elevenlabs"),
            enabled=bool(data.get("enabled", True)),
            priority=int(data.get("priority", 100)),
            active=bool(data.get("active", False)),
            has_saved_key=bool(data.get("has_saved_key", False)),
            account_tier=data.get("account_tier"),
            remaining_characters=data.get("remaining_characters"),
            character_limit=data.get("character_limit"),
            last_checked_at=data.get("last_checked_at"),
            last_success_at=data.get("last_success_at"),
            last_used_at=data.get("last_used_at"),
            last_error=data.get("last_error"),
            status=parsed_status,
            metadata=dict(data.get("metadata") or {}),
        )

    @staticmethod
    def _eligible_error(error_code: str | None) -> bool:
        return (error_code or "").lower() in {
            "insufficient_quota",
            "quota_exhausted",
            "invalid_api_key",
            "permission_denied",
            "paid_plan_required",
        }

    @staticmethod
    def _failover_mode(mode: str) -> ApiProfileFailoverMode:
        try:
            return ApiProfileFailoverMode(str(mode or "").lower())
        except ValueError:
            return ApiProfileFailoverMode.NEVER

    def _unique_name(self, display_name: str, provider: str) -> str:
        names = {profile.display_name.casefold() for profile in self.list_profiles(provider)}
        if display_name.casefold() not in names:
            return display_name
        index = 2
        while f"{display_name} {index}".casefold() in names:
            index += 1
        return f"{display_name} {index}"

    @staticmethod
    def _assert_unique_name(
        display_name: str,
        provider: str,
        *,
        exclude_id: str | None,
        profiles: list[ApiProfile],
    ) -> None:
        for profile in profiles:
            if profile.profile_id == exclude_id:
                continue
            if profile.provider == provider and profile.display_name.casefold() == display_name.casefold():
                raise ValueError(f"Profile name already exists for {provider}: {display_name}")
