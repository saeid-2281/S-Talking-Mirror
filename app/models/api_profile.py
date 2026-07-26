from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class ApiProfileStatus(StrEnum):
    READY = "ready"
    UNCHECKED = "unchecked"
    TESTING = "testing"
    EXHAUSTED = "exhausted"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class ApiProfileFailoverMode(StrEnum):
    NEVER = "never"
    PAUSE = "pause"
    AUTO = "auto"


@dataclass
class ApiProfile:
    profile_id: str
    display_name: str
    provider: str = "elevenlabs"
    enabled: bool = True
    priority: int = 100
    active: bool = False
    has_saved_key: bool = False
    account_tier: str | None = None
    remaining_characters: int | None = None
    character_limit: int | None = None
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_used_at: str | None = None
    last_error: str | None = None
    status: ApiProfileStatus = ApiProfileStatus.UNCHECKED
    metadata: dict[str, str] = field(default_factory=dict)

    def mark_checked(
        self,
        *,
        success: bool,
        account_tier: str | None = None,
        remaining_characters: int | None = None,
        character_limit: int | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.last_checked_at = now
        self.account_tier = account_tier
        self.remaining_characters = remaining_characters
        self.character_limit = character_limit
        self.last_error = error
        if success:
            self.last_success_at = now
            self.status = ApiProfileStatus.EXHAUSTED if remaining_characters == 0 else ApiProfileStatus.READY
        else:
            self.status = ApiProfileStatus.UNAVAILABLE if self.enabled else ApiProfileStatus.INVALID

    @property
    def masked_key(self) -> str:
        return "Saved key" if self.has_saved_key else "No saved key"

    @property
    def is_usable(self) -> bool:
        return self.enabled and self.has_saved_key and self.status not in {
            ApiProfileStatus.EXHAUSTED,
            ApiProfileStatus.UNAVAILABLE,
            ApiProfileStatus.INVALID,
        }


@dataclass(frozen=True)
class ProfileSwitchDecision:
    should_switch: bool
    target_profile_id: str | None = None
    reason: str = ""


@dataclass
class FailoverSettings:
    mode: ApiProfileFailoverMode = ApiProfileFailoverMode.NEVER
    max_switches_per_run: int = 1
    sequence_mode: str = "active_then_backups"
    manual_sequence: list[str] = field(default_factory=list)
    allow_unknown_quota_override: bool = False
