from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderRecoveryCandidate:
    provider_id: str
    provider_name: str
    rank: int
    score: int
    ready: bool
    eligible: bool
    locality: str
    status: str
    detail: str
    action_kind: str
    profile_id: str | None = None
    profile_name: str | None = None
    recommended_voice_id: str | None = None
    recommended_model_id: str | None = None
    language_state: str = "unknown"
    voice_state: str = "unknown"
    model_state: str = "unknown"
    account_state: str = "unknown"
    request_limit_state: str = "unknown"
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def actionable(self) -> bool:
        return bool(self.ready and self.eligible and not self.blockers)

    @property
    def evidence_text(self) -> str:
        return " · ".join(
            (
                f"language {self.language_state}",
                f"voice {self.voice_state}",
                f"model {self.model_state}",
                f"account {self.account_state}",
                f"limit {self.request_limit_state}",
            )
        )


@dataclass(frozen=True)
class ProviderRecoveryAssessment:
    assessment_id: str
    current_provider_id: str
    current_provider_name: str
    failure_summary: str
    failed_rows: tuple[int, ...]
    pending_rows: tuple[int, ...]
    scoped_jobs: int
    scoped_characters: int
    recommended_provider_id: str | None
    candidates: tuple[ProviderRecoveryCandidate, ...]
    created_at: str
    automatic_provider_switch: bool = False
    automatic_generation_restart: bool = False
    network_refresh_performed: bool = False

    @property
    def recoverable_rows(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys((*self.failed_rows, *self.pending_rows)))

    @property
    def actionable_candidates(self) -> tuple[ProviderRecoveryCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.actionable)

    def candidate_for(self, provider_id: str) -> ProviderRecoveryCandidate | None:
        normalized = str(provider_id or "").strip().casefold()
        return next((item for item in self.candidates if item.provider_id == normalized), None)


@dataclass(frozen=True)
class ProviderRecoveryReceipt:
    receipt_id: str
    assessment_id: str
    from_provider_id: str
    to_provider_id: str
    profile_id: str | None
    voice_id: str
    model_id: str
    language_code: str | None
    failed_rows: tuple[int, ...]
    created_at: str
    checksum: str
    path: str
    status: str = "prepared"
    user_approved: bool = True
    generation_started: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
