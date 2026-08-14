from __future__ import annotations

from dataclasses import dataclass

from app.exceptions import ConfigurationError
from app.models.domain import AppSettings, TTSJob
from app.services.pronunciation_assurance_service import PronunciationAssuranceService


@dataclass(frozen=True)
class PronunciationResult:
    original_text: str
    provider_text: str
    aid_applied: bool = False
    strategy: str = "none"
    dictionary_locators: tuple[dict[str, str], ...] = ()
    dictionary_fingerprint: str | None = None


class PronunciationService:
    """Provider-aware pronunciation preparation that preserves source truth.

    Source/job text is never mutated. A language-locked normalized provider form
    is used only after an explicit per-job ``normalized`` pronunciation override.
    """

    SHORT_WORD_LIMIT = 3
    SHORT_CHAR_LIMIT = 18

    def __init__(self) -> None:
        self.assurance = PronunciationAssuranceService()

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
        override = str(getattr(job, "pronunciation_override", None) or "").strip()
        decision = self.assurance.decision_kind(override)
        freshness = self.assurance.decision_freshness(job, settings)
        if override == "dictionary_disabled":
            return PronunciationResult(
                original_text=job.text,
                provider_text=job.text,
                aid_applied=False,
                strategy="dictionary_disabled",
            )

        if decision == "original":
            return PronunciationResult(
                original_text=job.text,
                provider_text=job.text,
                aid_applied=False,
                strategy="explicit_original",
                dictionary_locators=tuple(settings.pronunciation_dictionary_locators),
                dictionary_fingerprint=settings.active_pronunciation_dictionary_id,
            )

        if decision == "normalized":
            if self.assurance.decision_fingerprint(override) is not None and freshness != "current":
                raise ConfigurationError(
                    "Pronunciation normalized decision is stale for the current text/language/voice/model/dictionary context. "
                    "Revalidate the row explicitly before generation."
                )
            assessment = self.assurance.assess_job(job, settings)
            if assessment.normalization_safe and assessment.normalized_text != job.text:
                return PronunciationResult(
                    original_text=job.text,
                    provider_text=assessment.normalized_text,
                    aid_applied=True,
                    strategy=f"language_locked_{assessment.normalization_kind}",
                    dictionary_locators=tuple(settings.pronunciation_dictionary_locators),
                    dictionary_fingerprint=settings.active_pronunciation_dictionary_id,
                )
            return PronunciationResult(
                original_text=job.text,
                provider_text=job.text,
                aid_applied=False,
                strategy="normalization_unavailable",
                dictionary_locators=tuple(settings.pronunciation_dictionary_locators),
                dictionary_fingerprint=settings.active_pronunciation_dictionary_id,
            )

        return self.prepare(job.text, settings)

    def should_apply_danish_aid(self, text: str, settings: AppSettings) -> bool:
        assessment = self.assurance.assess(text, settings)
        return bool(settings.short_text_pronunciation_aid and assessment.normalization_safe)

    def strategy_for(self, settings: AppSettings) -> str:
        if settings.provider == "elevenlabs" and settings.pronunciation_dictionary_locators:
            return "elevenlabs_pronunciation_dictionary"
        if settings.provider == "elevenlabs" and (settings.language_code or "").lower() == "da":
            return "language_code_da"
        return "none"
