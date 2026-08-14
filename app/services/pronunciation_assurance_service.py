from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date

from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_assurance import (
    PronunciationAssessment,
    PronunciationBatchAssessment,
)


_INTEGER_RE = re.compile(r"^[+-]?\d{1,7}$")
_CURRENCY_RE = re.compile(
    r"^(?P<amount>\d{1,7}(?:[,.]\d{1,2})?)\s*(?P<unit>kr\.?|dkk)$",
    re.IGNORECASE,
)
_DATE_DMY_RE = re.compile(r"^(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})$")
_DATE_ISO_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")
_ACRONYM_RE = re.compile(r"^(?:[A-ZÆØÅ]{2,8}|(?:[A-ZÆØÅ]\.){2,8})$")
_ABBREVIATION_RE = re.compile(r"^(?:[A-Za-zÆØÅæøå]{1,5}\.)$")
_LATIN_LETTER_RE = re.compile(r"[A-Za-zÆØÅæøå]")
_NON_LATIN_LETTER_RE = re.compile(r"[^\W\d_A-Za-zÆØÅæøå]", re.UNICODE)
_SYMBOL_RE = re.compile(r"[^\w\sÆØÅæøå.,'’!?-]", re.UNICODE)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


class PronunciationAssuranceService:
    """Deterministic pronunciation-risk analysis locked to the chosen language.

    The service never detects or changes the target language, provider, account,
    voice or model. Normalization is conservative and only exposed as a candidate;
    execution requires an explicit per-job override handled by PronunciationService.
    """

    SHORT_WORD_LIMIT = 2
    SHORT_CHAR_LIMIT = 18

    _ONES = {
        0: "nul",
        1: "en",
        2: "to",
        3: "tre",
        4: "fire",
        5: "fem",
        6: "seks",
        7: "syv",
        8: "otte",
        9: "ni",
        10: "ti",
        11: "elleve",
        12: "tolv",
        13: "tretten",
        14: "fjorten",
        15: "femten",
        16: "seksten",
        17: "sytten",
        18: "atten",
        19: "nitten",
    }
    _TENS = {
        20: "tyve",
        30: "tredive",
        40: "fyrre",
        50: "halvtreds",
        60: "tres",
        70: "halvfjerds",
        80: "firs",
        90: "halvfems",
    }
    _ORDINAL_DAYS = {
        1: "første",
        2: "anden",
        3: "tredje",
        4: "fjerde",
        5: "femte",
        6: "sjette",
        7: "syvende",
        8: "ottende",
        9: "niende",
        10: "tiende",
        11: "ellevte",
        12: "tolvte",
        13: "trettende",
        14: "fjortende",
        15: "femtende",
        16: "sekstende",
        17: "syttende",
        18: "attende",
        19: "nittende",
        20: "tyvende",
        21: "enogtyvende",
        22: "toogtyvende",
        23: "treogtyvende",
        24: "fireogtyvende",
        25: "femogtyvende",
        26: "seksogtyvende",
        27: "syvogtyvende",
        28: "otteogtyvende",
        29: "niogtyvende",
        30: "tredivte",
        31: "enogtredivte",
    }
    _MONTHS = {
        1: "januar",
        2: "februar",
        3: "marts",
        4: "april",
        5: "maj",
        6: "juni",
        7: "juli",
        8: "august",
        9: "september",
        10: "oktober",
        11: "november",
        12: "december",
    }

    def assess(
        self,
        text: str,
        settings: AppSettings,
        *,
        row: int | None = None,
        language_code: str | None = None,
    ) -> PronunciationAssessment:
        source = str(text or "")
        stripped = source.strip()
        language = self._canonical_language(language_code if language_code is not None else settings.language_code)
        flags: list[str] = []
        words = _WORD_RE.findall(stripped)

        if stripped and (len(words) <= self.SHORT_WORD_LIMIT or len(stripped) <= self.SHORT_CHAR_LIMIT):
            flags.append("short_utterance")
        if any(char.isdigit() for char in stripped):
            flags.append("digits")
        if _CURRENCY_RE.fullmatch(stripped):
            flags.append("currency")
        if self._parse_date(stripped) is not None:
            flags.append("date")
        if _ACRONYM_RE.fullmatch(stripped):
            flags.append("acronym")
        elif _ABBREVIATION_RE.fullmatch(stripped):
            flags.append("abbreviation")
        if self._proper_name_like(stripped, words):
            flags.append("proper_name")
        if _SYMBOL_RE.search(stripped):
            flags.append("symbols")
        if language in self._LATIN_LANGUAGES and _NON_LATIN_LETTER_RE.search(stripped):
            flags.append("script_mismatch")
        if stripped and not _LATIN_LETTER_RE.search(stripped) and any(char.isalpha() for char in stripped) and language in self._LATIN_LANGUAGES:
            if "script_mismatch" not in flags:
                flags.append("script_mismatch")

        normalized_text = source
        normalization_kind = "none"
        normalization_safe = False
        if language == "da" and stripped:
            normalized = self._normalize_danish(stripped)
            if normalized is not None and normalized[0] != stripped:
                normalized_text, normalization_kind = normalized
                normalization_safe = True

        risk_level = self._risk_level(flags, normalization_safe)
        summary = self._summary(risk_level, flags, normalization_safe, normalization_kind)
        return PronunciationAssessment(
            row=row,
            language=language,
            original_text=source,
            normalized_text=normalized_text,
            normalization_kind=normalization_kind,
            normalization_safe=normalization_safe,
            risk_level=risk_level,
            flags=tuple(dict.fromkeys(flags)),
            summary=summary,
        )

    def assess_job(self, job: TTSJob, settings: AppSettings) -> PronunciationAssessment:
        language = str(getattr(job, "language_override", None) or settings.language_code or "").strip()
        return self.assess(job.text, settings, row=job.row_number, language_code=language)

    REVIEW_EVIDENCE_VERSION = "a74"

    def decision_kind(self, value: str | None) -> str:
        raw = str(value or "").strip()
        for kind in ("original", "normalized"):
            if raw == kind or raw.startswith(f"{kind}@{self.REVIEW_EVIDENCE_VERSION}:"):
                return kind
        return raw

    def decision_fingerprint(self, value: str | None) -> str | None:
        raw = str(value or "").strip()
        marker = f"@{self.REVIEW_EVIDENCE_VERSION}:"
        if marker not in raw:
            return None
        kind, fingerprint = raw.split(marker, 1)
        if kind not in {"original", "normalized"} or not fingerprint:
            return None
        return fingerprint

    def review_context_fingerprint(self, job: TTSJob, settings: AppSettings) -> str:
        language = str(getattr(job, "language_override", None) or settings.language_code or "").strip()
        payload = {
            "schema": self.REVIEW_EVIDENCE_VERSION,
            "text": str(job.text or ""),
            "language": self._canonical_language(language),
            "provider": str(settings.provider or ""),
            "voice_id": str(settings.voice_id or ""),
            "model_id": str(settings.model_id or ""),
            "dictionary_id": str(settings.active_pronunciation_dictionary_id or ""),
            "dictionary_locators": list(settings.pronunciation_dictionary_locators),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def encode_review_decision(self, decision: str, job: TTSJob, settings: AppSettings) -> str:
        kind = self.decision_kind(decision)
        if kind not in {"original", "normalized"}:
            raise ValueError("Only original or normalized pronunciation review decisions can be versioned.")
        return f"{kind}@{self.REVIEW_EVIDENCE_VERSION}:{self.review_context_fingerprint(job, settings)}"

    def decision_freshness(self, job: TTSJob, settings: AppSettings) -> str:
        raw = str(getattr(job, "pronunciation_override", None) or "").strip()
        kind = self.decision_kind(raw)
        if kind not in {"original", "normalized"}:
            return "none"
        fingerprint = self.decision_fingerprint(raw)
        if fingerprint is None:
            return "legacy"
        return "current" if fingerprint == self.review_context_fingerprint(job, settings) else "stale"

    def assess_batch(
        self,
        jobs: list[TTSJob],
        settings: AppSettings,
        *,
        require_freshness: bool = False,
    ) -> PronunciationBatchAssessment:
        assessments = tuple(self.assess_job(job, settings) for job in jobs)
        counts = Counter(flag for item in assessments for flag in item.flags)
        languages = tuple(sorted({item.language for item in assessments if item.language}))
        pairs = tuple(zip(jobs, assessments, strict=True))
        freshness = {job.row_number: self.decision_freshness(job, settings) for job, _item in pairs}
        kinds = {
            job.row_number: self.decision_kind(str(getattr(job, "pronunciation_override", None) or "").strip())
            for job, _item in pairs
        }
        current = tuple(sorted(row for row, status in freshness.items() if status == "current"))
        stale = tuple(sorted(row for row, status in freshness.items() if status == "stale"))
        legacy = tuple(sorted(row for row, status in freshness.items() if status == "legacy"))

        def accepted(job: TTSJob, item: PronunciationAssessment) -> bool:
            kind = kinds[job.row_number]
            if kind == "normalized" and not item.normalization_safe:
                return False
            if kind not in {"original", "normalized"}:
                return False
            return freshness[job.row_number] == "current" if require_freshness else True

        explicit_original = tuple(
            job.row_number
            for job, item in pairs
            if kinds[job.row_number] == "original" and accepted(job, item)
        )
        normalized = tuple(
            job.row_number
            for job, item in pairs
            if kinds[job.row_number] == "normalized" and item.normalization_safe and accepted(job, item)
        )
        reviewed_set = set(explicit_original) | set(normalized)
        unresolved = tuple((job, item) for job, item in pairs if job.row_number not in reviewed_set)
        high = tuple(
            item.row
            for _job, item in unresolved
            if item.row is not None and item.risk_level == "high"
        )
        medium = tuple(
            item.row
            for _job, item in unresolved
            if item.row is not None and item.risk_level == "medium"
        )
        normalizable = tuple(item.row for item in assessments if item.row is not None and item.normalization_safe)
        unsafe = tuple(
            job.row_number
            for job, item in pairs
            if kinds[job.row_number] == "normalized" and not item.normalization_safe
        )
        reviewed = tuple(sorted(reviewed_set))
        risk_count = len(high) + len(medium)
        if require_freshness:
            stale_count = len(stale) + len(legacy)
            summary = (
                f"Pronunciation review: {risk_count}/{len(assessments)} job(s) need review; "
                f"{len(reviewed)} explicit decision(s) current; "
                f"{stale_count} decision(s) need revalidation; "
                f"{len(normalizable)} have a safe language-locked normalized form; "
                f"languages: {', '.join(languages) if languages else 'not set'}."
            )
        else:
            summary = (
                f"Pronunciation review: {risk_count}/{len(assessments)} job(s) need review; "
                f"{len(reviewed)} explicit decision(s) recorded; "
                f"{len(normalizable)} have a safe language-locked normalized form; "
                f"languages: {', '.join(languages) if languages else 'not set'}."
            )
        return PronunciationBatchAssessment(
            assessments=assessments,
            languages=languages,
            high_risk_rows=high,
            medium_risk_rows=medium,
            normalizable_rows=normalizable,
            reviewed_rows=reviewed,
            current_review_rows=current,
            stale_review_rows=stale,
            legacy_review_rows=legacy,
            explicit_original_rows=explicit_original,
            normalized_rows=normalized,
            unsafe_normalization_rows=unsafe,
            counts=dict(sorted(counts.items())),
            summary=summary,
        )

    def _normalize_danish(self, text: str) -> tuple[str, str] | None:
        currency = _CURRENCY_RE.fullmatch(text)
        if currency:
            amount = currency.group("amount").replace(",", ".")
            try:
                whole_text, _, decimal_text = amount.partition(".")
                whole = int(whole_text)
                if whole > 999_999:
                    return None
                whole_words = self._danish_integer(whole)
                unit = "krone" if whole == 1 else "kroner"
                if decimal_text:
                    ore = int(decimal_text.ljust(2, "0")[:2])
                    if ore:
                        ore_words = self._danish_integer(ore)
                        ore_unit = "øre"
                        return f"{whole_words} {unit} og {ore_words} {ore_unit}", "currency"
                return f"{whole_words} {unit}", "currency"
            except (TypeError, ValueError):
                return None

        parsed = self._parse_date(text)
        if parsed is not None:
            day, month, year = parsed.day, parsed.month, parsed.year
            return (
                f"den {self._ORDINAL_DAYS[day]} {self._MONTHS[month]} {self._danish_integer(year)}",
                "date",
            )

        if _INTEGER_RE.fullmatch(text):
            try:
                value = int(text)
            except ValueError:
                return None
            if 0 <= value <= 999_999:
                return self._danish_integer(value), "integer"
        return None

    def _danish_integer(self, value: int) -> str:
        if value < 0 or value > 999_999:
            raise ValueError("Danish integer normalization supports 0..999999")
        if value < 20:
            return self._ONES[value]
        if value < 100:
            tens = value // 10 * 10
            ones = value % 10
            return self._TENS[tens] if not ones else f"{self._ONES[ones]}og{self._TENS[tens]}"
        if value < 1000:
            hundreds, rest = divmod(value, 100)
            prefix = "et hundrede" if hundreds == 1 else f"{self._danish_integer(hundreds)} hundrede"
            return prefix if not rest else f"{prefix} og {self._danish_integer(rest)}"
        thousands, rest = divmod(value, 1000)
        prefix = "et tusind" if thousands == 1 else f"{self._danish_integer(thousands)} tusind"
        if not rest:
            return prefix
        connector = " og " if rest < 100 else " "
        return f"{prefix}{connector}{self._danish_integer(rest)}"

    @staticmethod
    def _parse_date(text: str) -> date | None:
        match = _DATE_DMY_RE.fullmatch(text)
        if match:
            parts = {key: int(value) for key, value in match.groupdict().items()}
        else:
            match = _DATE_ISO_RE.fullmatch(text)
            if not match:
                return None
            parts = {key: int(value) for key, value in match.groupdict().items()}
        try:
            return date(parts["year"], parts["month"], parts["day"])
        except ValueError:
            return None

    @staticmethod
    def _proper_name_like(text: str, words: list[str]) -> bool:
        if not text or not words or _ACRONYM_RE.fullmatch(text):
            return False
        if not 2 <= len(words) <= 3:
            return False
        return all(word[:1].isupper() and not word.isupper() for word in words)

    @staticmethod
    def _risk_level(flags: list[str], normalization_safe: bool) -> str:
        flag_set = set(flags)
        if "script_mismatch" in flag_set:
            return "high"
        if flag_set & {"acronym", "abbreviation", "proper_name", "symbols"}:
            return "high" if "short_utterance" in flag_set else "medium"
        if flag_set & {"currency", "date", "digits"}:
            return "medium" if normalization_safe else "high"
        if "short_utterance" in flag_set:
            return "low"
        return "low"

    @staticmethod
    def _summary(risk: str, flags: list[str], safe: bool, kind: str) -> str:
        labels = ", ".join(flags) if flags else "plain prose"
        normalized = f" Safe {kind} normalization is available." if safe else ""
        return f"{risk.title()} pronunciation risk: {labels}.{normalized}"

    @staticmethod
    def _canonical_language(value: str | None) -> str:
        language = str(value or "").strip().lower().replace("_", "-")
        return language.split("-", 1)[0] if language else ""

    _LATIN_LANGUAGES = {
        "da",
        "de",
        "en",
        "es",
        "fi",
        "fr",
        "is",
        "it",
        "nl",
        "no",
        "pt",
        "sv",
        "tr",
    }
