from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import AppSettings, TTSJob


@dataclass(frozen=True)
class PronunciationResult:
    original_text: str
    provider_text: str
    aid_applied: bool = False
    strategy: str = "none"
    dictionary_locators: tuple[dict[str, str], ...] = ()
    dictionary_fingerprint: str | None = None


class PronunciationService:
    """Provider-aware pronunciation metadata that never rewrites source text."""

    SHORT_WORD_LIMIT = 3
    SHORT_CHAR_LIMIT = 18

    def prepare(self, text: str, settings: AppSettings) -> PronunciationResult:
        return PronunciationResult(
            original_text=text,
            provider_text=text,
            aid_applied=False,
            strategy=self.strategy_for(settings),
            dictionary_locators=tuple(settings.pronunciation_dictionary_locators),
            dictionary_fingerprint=settings.active_pronunciation_dictionary_id,
        )

    def prepare_job(self, job: TTSJob, settings: AppSettings) -> PronunciationResult:
        if getattr(job, "pronunciation_override", None) == "dictionary_disabled":
            return PronunciationResult(
                original_text=job.text,
                provider_text=job.text,
                aid_applied=False,
                strategy="dictionary_disabled",
            )
        return self.prepare(job.text, settings)

    def should_apply_danish_aid(self, text: str, settings: AppSettings) -> bool:
        return False

    def strategy_for(self, settings: AppSettings) -> str:
        if settings.provider == "elevenlabs" and settings.pronunciation_dictionary_locators:
            return "elevenlabs_pronunciation_dictionary"
        if settings.provider == "elevenlabs" and (settings.language_code or "").lower() == "da":
            return "language_code_da"
        return "none"
