from __future__ import annotations

import re
from collections import defaultdict

from app.models.domain import AppSettings, TTSJob
from app.models.language_assurance import (
    BatchLanguageAssurance,
    LanguageAssuranceDecision,
    LanguageAssuranceLevel,
)
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.cartesia import CARTESIA_LANGUAGES
from app.providers.resemble import RESEMBLE_DOCUMENTED_LOCALES


class LanguageAssuranceService:
    """Resolve the user-selected language without automatic language detection.

    The selected project language (or an explicit per-job language override) is
    authoritative. Provider-specific adaptation may change only the *syntax* of
    the language token sent to the selected provider; it never selects another
    provider, account, voice, model, or target language.
    """

    _LOCALE_DEFAULTS = {
        "da": "da-DK",
        "en": "en-US",
        "de": "de-DE",
        "sv": "sv-SE",
        "no": "nb-NO",
        "nb": "nb-NO",
        "tr": "tr-TR",
        "es": "es-ES",
        "fr": "fr-FR",
        "fi": "fi-FI",
        "nl": "nl-NL",
        "pl": "pl-PL",
        "pt": "pt-PT",
        "it": "it-IT",
        "cs": "cs-CZ",
    }
    _BASE_TOKEN_PROVIDERS = {"elevenlabs", "cartesia", "deepgram"}
    _LOCALE_TOKEN_PROVIDERS = {"azure", "google", "aws_polly", "murf"}
    _OPENAI_LEGACY_MODELS = {"tts-1", "tts-1-hd"}
    _LOCALE_PREFIX = re.compile(r"^([a-z]{2,3})-([A-Za-z]{2})(?:-|$)")

    def effective_language(self, job: TTSJob | None, settings: AppSettings) -> str:
        value = (
            str(getattr(job, "language_override", "") or "").strip()
            if job is not None
            else ""
        )
        return value or str(settings.language_code or "").strip()

    def canonical_language(self, value: str | None) -> str:
        raw = str(value or "").strip().replace("_", "-")
        if not raw:
            return ""
        parts = [part for part in raw.split("-") if part]
        if not parts:
            return ""
        normalized = [parts[0].lower()]
        for part in parts[1:]:
            if len(part) == 2 and part.isalpha():
                normalized.append(part.upper())
            elif len(part) == 4 and part.isalpha():
                normalized.append(part.title())
            else:
                normalized.append(part)
        return "-".join(normalized)

    def base_language(self, value: str | None) -> str:
        canonical = self.canonical_language(value)
        return canonical.split("-", 1)[0].casefold() if canonical else ""

    def locale_language(self, value: str | None) -> str:
        canonical = self.canonical_language(value)
        if not canonical:
            return ""
        if "-" in canonical:
            return canonical
        return self._LOCALE_DEFAULTS.get(canonical.casefold(), canonical)

    def provider_language(self, provider_id: str, value: str | None) -> str:
        provider = str(provider_id or "").strip().casefold()
        if provider in self._BASE_TOKEN_PROVIDERS:
            return self.base_language(value)
        if provider in self._LOCALE_TOKEN_PROVIDERS:
            return self.locale_language(value)
        if provider == "resemble":
            return self.locale_language(value).casefold()
        return self.canonical_language(value)

    def settings_for_job(self, job: TTSJob, settings: AppSettings) -> AppSettings:
        requested = self.effective_language(job, settings)
        provider_language = self.provider_language(settings.provider, requested)
        updates: dict[str, object] = {
            "language_code": provider_language or None,
        }

        if (
            settings.provider == "openai"
            and provider_language
            and str(settings.model_id or "").strip().casefold()
            not in self._OPENAI_LEGACY_MODELS
        ):
            options = dict(settings.provider_options)
            existing = str(options.get("instructions") or "").strip()
            directive = self._openai_language_instruction(
                self.canonical_language(requested) or provider_language
            )
            if directive.casefold() not in existing.casefold():
                options["instructions"] = (
                    f"{existing}\n{directive}".strip() if existing else directive
                )
            updates["provider_options"] = options

        return settings.model_copy(update=updates)

    def assess_batch(
        self,
        jobs: list[TTSJob],
        settings: AppSettings,
    ) -> BatchLanguageAssurance:
        grouped: dict[str, list[int]] = defaultdict(list)
        if jobs:
            for job in jobs:
                language = self.effective_language(job, settings)
                grouped[language].append(job.row_number)
        else:
            grouped[self.effective_language(None, settings)] = []

        decisions = tuple(
            self.assess(
                settings,
                language,
                rows=tuple(rows),
            )
            for language, rows in grouped.items()
        )
        levels: tuple[LanguageAssuranceLevel, ...] = tuple(
            item.assurance_level for item in decisions
        )
        rank = {"none": 0, "best_effort": 1, "bounded": 2, "strong": 3}
        overall: LanguageAssuranceLevel = (
            min(levels, key=lambda item: rank[item]) if levels else "none"
        )
        languages = tuple(
            dict.fromkeys(
                item.canonical_language or item.requested_language
                for item in decisions
                if item.canonical_language or item.requested_language
            )
        )
        return BatchLanguageAssurance(
            decisions=decisions,
            languages=languages,
            overall_level=overall,
        )

    def assess(
        self,
        settings: AppSettings,
        requested_language: str,
        *,
        rows: tuple[int, ...] = (),
    ) -> LanguageAssuranceDecision:
        provider = str(settings.provider or "").strip().casefold()
        canonical = self.canonical_language(requested_language)
        provider_token = self.provider_language(provider, requested_language)
        base = self.base_language(requested_language)
        model = str(settings.model_id or "").strip()
        voice = str(settings.voice_id or "").strip()

        if not canonical:
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "unknown",
                "none",
                rows,
                blocking=True,
                code="language_lock_missing",
                message="No explicit target language is selected for this generation scope.",
                action="Choose the intended language before running Preflight.",
            )

        if provider == "mock":
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "test_only",
                "strong",
                rows,
                code="language_lock_test_provider",
                message=f"Mock generation is locked to the explicit test language {canonical}.",
            )

        if provider == "cartesia":
            if base not in CARTESIA_LANGUAGES:
                return self._unsupported(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    rows,
                    f"Cartesia does not support the requested language token {base!r}.",
                )
            return self._strong(
                provider,
                requested_language,
                canonical,
                provider_token,
                "explicit_parameter",
                rows,
                "Cartesia receives the explicit language parameter for this request.",
            )

        if provider == "elevenlabs":
            if "multilingual_v2" in model.casefold():
                return self._decision(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    "unknown",
                    "best_effort",
                    rows,
                    code="language_lock_model_limited",
                    message=(
                        "The selected ElevenLabs multilingual_v2 model does not provide "
                        "a reliable explicit language-lock contract; provider language detection remains involved."
                    ),
                    action=(
                        "Choose an ElevenLabs model that supports explicit language_code "
                        "when strict language locking is required."
                    ),
                )
            return self._strong(
                provider,
                requested_language,
                canonical,
                provider_token,
                "explicit_parameter",
                rows,
                "ElevenLabs receives the explicit ISO language token for this request.",
            )

        if provider == "openai":
            if model.casefold() in self._OPENAI_LEGACY_MODELS:
                return self._decision(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    "unknown",
                    "none",
                    rows,
                    code="language_lock_provider_limited",
                    message=(
                        "The selected legacy OpenAI Speech model exposes no explicit "
                        "language parameter or instruction control."
                    ),
                    action=(
                        "Use a speech model with instruction support or choose a provider "
                        "with explicit language enforcement when strict locking is required."
                    ),
                )
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "instruction",
                "best_effort",
                rows,
                code="language_lock_instruction_only",
                message=(
                    f"S-Talking will add an explicit {canonical} pronunciation instruction "
                    "without translating or rewriting the source text."
                ),
                action="Review the Language Assurance warning before launch.",
            )

        if provider == "deepgram":
            model_language = self._deepgram_model_language(model)
            if base and model_language and base != model_language:
                return self._decision(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    "model_bound",
                    "none",
                    rows,
                    blocking=True,
                    code="language_model_mismatch",
                    message=(
                        f"Deepgram model {model or 'not selected'} is bound to "
                        f"{model_language}, not {base}."
                    ),
                    action="Choose a Deepgram model whose language matches the explicit target language.",
                )
            return self._strong(
                provider,
                requested_language,
                canonical,
                provider_token,
                "model_bound",
                rows,
                "Deepgram language is bound by the explicitly selected Aura model.",
            )

        if provider == "azure":
            voice_locale = self._voice_locale(voice)
            if voice_locale and not self._language_matches(canonical, voice_locale):
                return self._voice_mismatch(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    rows,
                    voice_locale,
                )
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "ssml_locale",
                "strong" if voice_locale else "bounded",
                rows,
                code="language_lock_ssml",
                message=(
                    f"Azure receives xml:lang={provider_token}; "
                    + (
                        f"selected voice locale {voice_locale} matches."
                        if voice_locale
                        else "voice locale could not be verified statically."
                    )
                ),
                action="Use a voice from the same locale as the target language.",
            )

        if provider == "google":
            voice_locale = self._voice_locale(voice)
            if voice_locale and not self._language_matches(canonical, voice_locale):
                return self._voice_mismatch(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    rows,
                    voice_locale,
                )
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "voice_bound",
                "bounded",
                rows,
                code="language_lock_voice_bound",
                message=(
                    f"Google receives language_code={provider_token}"
                    + (f" with matching voice locale {voice_locale}." if voice_locale else ".")
                ),
                action="Keep the selected Google voice locale aligned with the target language.",
            )

        if provider == "aws_polly":
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "voice_bound",
                "bounded",
                rows,
                code="language_lock_voice_bound",
                message=(
                    f"Amazon Polly receives the explicit target locale {provider_token}; "
                    "the selected voice remains authoritative for non-bilingual voice language."
                ),
                action="Verify the selected Polly voice supports the target locale.",
            )

        if provider == "murf":
            return self._strong(
                provider,
                requested_language,
                canonical,
                provider_token,
                "explicit_parameter",
                rows,
                f"Murf receives the explicit locale {provider_token}; provider validation still checks supported synthesis configuration.",
            )

        if provider == "resemble":
            if provider_token and provider_token not in RESEMBLE_DOCUMENTED_LOCALES:
                return self._unsupported(
                    provider,
                    requested_language,
                    canonical,
                    provider_token,
                    rows,
                    f"Resemble locale {provider_token!r} is not in the documented adapter locale contract.",
                )
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "ssml_locale",
                "bounded",
                rows,
                code="language_lock_ssml_voice_bound",
                message=(
                    f"Resemble receives SSML language {provider_token}; "
                    "the selected voice remains authoritative for language support."
                ),
                action="Use a Resemble voice verified for the target locale.",
            )

        if provider in {"piper", "kokoro"}:
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "model_bound",
                "bounded",
                rows,
                code="language_lock_model_bound",
                message=(
                    f"{provider.replace('_', ' ').title()} language is bound by the explicitly selected local voice/model."
                ),
                action="Keep the local model language aligned with the explicit target language.",
            )

        manifest = DEFAULT_PROVIDER_REGISTRY.manifest_for(provider)
        if manifest.supports_language_code_fallback:
            return self._decision(
                provider,
                requested_language,
                canonical,
                provider_token,
                "explicit_parameter",
                "bounded",
                rows,
                code="language_lock_plugin_bounded",
                message=(
                    f"{manifest.display_name} declares language-code support, but "
                    "S-Talking has no stronger built-in enforcement contract for this provider."
                ),
                action="Verify the provider plugin language contract before strict production use.",
            )

        return self._decision(
            provider,
            requested_language,
            canonical,
            provider_token,
            "unknown",
            "best_effort",
            rows,
            code="language_lock_unverified",
            message="The selected provider has no verified language-enforcement contract in S-Talking.",
            action="Choose a provider with a verified language-enforcement contract.",
        )

    @classmethod
    def _voice_locale(cls, voice_id: str) -> str:
        match = cls._LOCALE_PREFIX.match(str(voice_id or "").strip())
        if not match:
            return ""
        return f"{match.group(1).lower()}-{match.group(2).upper()}"

    def _language_matches(self, requested: str, available: str) -> bool:
        requested_canonical = self.canonical_language(requested)
        available_canonical = self.canonical_language(available)
        if not requested_canonical or not available_canonical:
            return True
        if requested_canonical.casefold() == available_canonical.casefold():
            return True
        return self.base_language(requested_canonical) == self.base_language(available_canonical)

    @staticmethod
    def _deepgram_model_language(model_id: str) -> str:
        token = str(model_id or "").strip().casefold()
        if not token.startswith("aura-") or "-" not in token:
            return ""
        return token.rsplit("-", 1)[-1]

    @staticmethod
    def _openai_language_instruction(language: str) -> str:
        return (
            f"Use {language} pronunciation, number-reading, abbreviation, date, and "
            "locale conventions for the provided input. Do not translate, paraphrase, "
            "or rewrite the input."
        )

    def _strong(
        self,
        provider: str,
        requested: str,
        canonical: str,
        provider_token: str,
        mode: str,
        rows: tuple[int, ...],
        message: str,
    ) -> LanguageAssuranceDecision:
        return self._decision(
            provider,
            requested,
            canonical,
            provider_token,
            mode,
            "strong",
            rows,
            code="language_lock_strong",
            message=message,
        )

    def _unsupported(
        self,
        provider: str,
        requested: str,
        canonical: str,
        provider_token: str,
        rows: tuple[int, ...],
        message: str,
    ) -> LanguageAssuranceDecision:
        return self._decision(
            provider,
            requested,
            canonical,
            provider_token,
            "explicit_parameter",
            "none",
            rows,
            blocking=True,
            code="language_not_supported",
            message=message,
            action="Choose a supported target language, voice, or model.",
        )

    def _voice_mismatch(
        self,
        provider: str,
        requested: str,
        canonical: str,
        provider_token: str,
        rows: tuple[int, ...],
        voice_locale: str,
    ) -> LanguageAssuranceDecision:
        return self._decision(
            provider,
            requested,
            canonical,
            provider_token,
            "voice_bound",
            "none",
            rows,
            blocking=True,
            code="language_voice_mismatch",
            message=(
                f"Selected voice locale {voice_locale} does not match explicit target language {canonical}."
            ),
            action="Choose a voice whose locale matches the explicit target language.",
        )

    @staticmethod
    def _decision(
        provider: str,
        requested: str,
        canonical: str,
        provider_token: str,
        mode: str,
        level: LanguageAssuranceLevel,
        rows: tuple[int, ...],
        *,
        blocking: bool = False,
        code: str,
        message: str,
        action: str = "",
    ) -> LanguageAssuranceDecision:
        return LanguageAssuranceDecision(
            provider_id=provider,
            requested_language=str(requested or ""),
            canonical_language=canonical,
            provider_language=provider_token,
            enforcement_mode=mode,
            assurance_level=level,
            blocking=blocking,
            code=code,
            message=message,
            suggested_action=action,
            rows=rows,
        )
