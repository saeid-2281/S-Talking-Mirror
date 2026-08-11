from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, cast

from app.config.runtime import RuntimeConfig
from app.models.danish_provider_benchmark import (
    DanishBenchmarkCase,
    DanishBenchmarkRating,
    DanishCertificationState,
    DanishDocumentationEvidence,
    DanishDocumentationState,
    DanishProviderBenchmarkSnapshot,
    DanishProviderCertification,
)
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


class DanishProviderBenchmarkService:
    """Human-reviewed Danish TTS benchmark and certification evidence.

    The service is deliberately offline-by-default. Reading a snapshot never
    refreshes a provider, spends credits, calls a billing API, or synthesizes
    audio. A human reviewer explicitly records ratings produced from the fixed
    corpus using the chosen provider/voice/model.
    """

    LANGUAGE_CODE = "da-DK"
    SCHEMA_VERSION = 1
    MINIMUM_CASES = 10
    PASS_SCORE = 80.0
    CONDITIONAL_SCORE = 70.0
    CRITICAL_MINIMUM = 3
    CHECKED_ON = "2026-08-11"

    CORPUS: tuple[DanishBenchmarkCase, ...] = (
        DanishBenchmarkCase(
            "everyday",
            "Everyday Danish",
            "Hej, jeg hedder Maja, og jeg bor i Aarhus sammen med min familie.",
            critical=True,
            guidance="Natural Danish rhythm, vowels and sentence melody.",
        ),
        DanishBenchmarkCase(
            "numbers",
            "Numbers",
            "Ordrenummeret er 47 318, og beløbet er 1.249,50 kroner.",
            critical=True,
            guidance="Danish number pronunciation and decimal conventions.",
        ),
        DanishBenchmarkCase(
            "dates",
            "Dates and time",
            "Mødet er tirsdag den 18. august 2026 klokken 14.35.",
            critical=True,
            guidance="Date, year and clock-time rendering.",
        ),
        DanishBenchmarkCase(
            "compounds",
            "Compound words",
            "Arbejdsmiljørepræsentanten gennemgår sikkerhedsprocedurerne på arbejdspladsen.",
            critical=True,
            guidance="Long Danish compounds without syllable collapse.",
        ),
        DanishBenchmarkCase(
            "places",
            "Danish place names",
            "Toget kører fra København gennem Odense til Sønderborg og Aarhus.",
            critical=True,
            guidance="Danish place-name vowels, stød and stress.",
        ),
        DanishBenchmarkCase(
            "letters",
            "Abbreviations",
            "DSB og DR samarbejder om information, mens EU-reglerne stadig gælder.",
            guidance="Letter names and abbreviation handling.",
        ),
        DanishBenchmarkCase(
            "question",
            "Question prosody",
            "Kan du forklare, hvorfor toget blev forsinket, og hvornår det kommer?",
            critical=True,
            guidance="Question intonation without losing clause boundaries.",
        ),
        DanishBenchmarkCase(
            "long_sentence",
            "Long-form narration",
            "Selv om vejret ændrede sig hurtigt, valgte vi at fortsætte turen, fordi udsigten over fjorden stadig var klar og rolig.",
            guidance="Breathing, pauses and stable long-sentence prosody.",
        ),
        DanishBenchmarkCase(
            "minimal_pairs",
            "Danish phonetics",
            "Rødgrød med fløde står på bordet ved siden af brød, smør og grønne æbler.",
            critical=True,
            guidance="Danish vowels, soft d and dense consonant transitions.",
        ),
        DanishBenchmarkCase(
            "names",
            "Names",
            "Sofie, Jeppe, Mads og Naja mødes med Christel efter arbejdet.",
            guidance="Common Danish names and stable proper-noun stress.",
        ),
        DanishBenchmarkCase(
            "code_switch",
            "Code switching",
            "Vi sender rapporten som PDF og tager derefter et kort online meeting med teamet.",
            guidance="Natural Danish with embedded English/technical terms.",
        ),
        DanishBenchmarkCase(
            "punctuation",
            "Punctuation",
            "Først: kontrollér filen. Derefter—hvis alt er korrekt—kan du trykke på Start.",
            guidance="Colon, dash and instruction pacing.",
        ),
    )

    DOCUMENTATION: Mapping[str, DanishDocumentationEvidence] = {
        "mock": DanishDocumentationEvidence(
            "mock", "test_only", "Mock test provider", "S-Talking internal test provider", "", CHECKED_ON,
            "Mock is not a production Danish TTS certification target.",
        ),
        "piper": DanishDocumentationEvidence(
            "piper", "runtime_dependent", "Danish voice packs documented", "OHF-Voice Piper voices", "https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md", CHECKED_ON,
            "Piper documents da_DK voices; certification is voice-pack specific and must preserve the MODEL_CARD license evidence.",
        ),
        "elevenlabs": DanishDocumentationEvidence(
            "elevenlabs", "documented", "Danish documented", "ElevenLabs language support", "https://elevenlabs.io/docs/help-center/other/what-languages-do-you-support", CHECKED_ON,
            "Danish is listed for multilingual speech models. Human benchmark certification is still required.",
        ),
        "openai": DanishDocumentationEvidence(
            "openai", "documented", "Danish documented", "OpenAI Text to speech", "https://developers.openai.com/api/docs/guides/text-to-speech", CHECKED_ON,
            "Danish is supported; OpenAI notes that built-in voices are optimized for English, so quality certification remains benchmark-based.",
        ),
        "azure": DanishDocumentationEvidence(
            "azure", "documented", "da-DK documented", "Azure Speech language and voice support", "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support", CHECKED_ON,
            "Azure documents Danish (Denmark) text-to-speech voices.",
        ),
        "google": DanishDocumentationEvidence(
            "google", "documented", "da-DK documented", "Google Cloud TTS voices", "https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types", CHECKED_ON,
            "Google Cloud TTS documents Danish (Denmark), including Chirp 3 HD voices.",
        ),
        "aws_polly": DanishDocumentationEvidence(
            "aws_polly", "documented", "da-DK documented", "Amazon Polly available voices", "https://docs.aws.amazon.com/polly/latest/dg/available-voices.html", CHECKED_ON,
            "Amazon Polly documents Danish voices; engine/voice combinations still need benchmark evidence.",
        ),
        "kokoro": DanishDocumentationEvidence(
            "kokoro", "unsupported", "Danish not in certified runtime set", "Kokoro runtime contract", "", CHECKED_ON,
            "The S-Talking Kokoro runtime deliberately blocks Danish because the supported Kokoro language set does not include it.",
        ),
        "cartesia": DanishDocumentationEvidence(
            "cartesia", "documented", "Danish documented", "Cartesia Sonic 3.5", "https://docs.cartesia.ai/build-with-cartesia/tts-models/latest", CHECKED_ON,
            "Sonic 3.5 explicitly lists Danish (da); benchmark certification is voice/model specific.",
        ),
        "deepgram": DanishDocumentationEvidence(
            "deepgram", "unsupported", "Danish not documented for Aura TTS", "Deepgram TTS voices and languages", "https://developers.deepgram.com/docs/tts-models", CHECKED_ON,
            "Deepgram Aura TTS currently documents English, Spanish, German, French, Dutch, Italian and Japanese, not Danish.",
        ),
        "resemble": DanishDocumentationEvidence(
            "resemble", "documented", "da-dk documented", "Resemble SSML reference", "https://docs.resemble.ai/getting-started/ssml", CHECKED_ON,
            "Resemble documents Danish (Denmark) da-dk in its language locale contract.",
        ),
        "murf": DanishDocumentationEvidence(
            "murf", "not_explicit", "Danish TTS certification pending", "Murf Gen2 TTS model documentation", "https://murf.ai/api/docs/text-to-speech-models/gen-2", CHECKED_ON,
            "Murf documents multilingual Gen2 and many voice locales, but the reviewed TTS model page does not explicitly enumerate Danish as a model-level contract; keep S-Talking Danish certification pending until benchmark evidence is reviewed.",
        ),
    }

    def __init__(
        self,
        runtime: RuntimeConfig,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.runtime = runtime
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY
        self.root = runtime.artifacts_dir / "danish-provider-benchmark"
        self.certifications_dir = self.root / "certifications"
        self.exports_dir = self.root / "exports"
        self.root.mkdir(parents=True, exist_ok=True)
        self.certifications_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def documentation_for(self, provider_id: str) -> DanishDocumentationEvidence:
        normalized = str(provider_id or "unknown").strip().casefold() or "unknown"
        evidence = self.DOCUMENTATION.get(normalized)
        if evidence is not None:
            return evidence
        return DanishDocumentationEvidence(
            normalized,
            "unknown",
            "Documentation not reviewed",
            "No Phase 109 evidence source",
            "",
            self.CHECKED_ON,
            "No curated Danish documentation evidence exists for this provider.",
        )

    def export_corpus(self) -> Path:
        payload = {
            "document_schema_version": self.SCHEMA_VERSION,
            "language_code": self.LANGUAGE_CODE,
            "minimum_cases": self.MINIMUM_CASES,
            "pass_score": self.PASS_SCORE,
            "critical_minimum": self.CRITICAL_MINIMUM,
            "cases": [item.to_dict() for item in self.CORPUS],
            "policy": {
                "automatic_synthesis": False,
                "automatic_provider_switch": False,
                "automatic_certification": False,
                "human_review_required": True,
            },
        }
        path = self.exports_dir / "danish-benchmark-corpus.json"
        self._write_json(path, payload)
        return path

    def save_evaluation(
        self,
        provider_id: str,
        ratings: Iterable[DanishBenchmarkRating],
        *,
        reviewer: str,
        voice_id: str,
        model_id: str,
        note: str = "",
    ) -> DanishProviderCertification:
        normalized = str(provider_id or "").strip().casefold()
        if not normalized:
            raise ValueError("provider_id is required")
        reviewer = str(reviewer or "").strip()
        if not reviewer:
            raise ValueError("reviewer is required")
        evidence = self.documentation_for(normalized)
        if evidence.state in {"unsupported", "test_only"}:
            raise ValueError(f"{normalized} cannot be certified for Danish from the current documented contract")

        case_by_id = {item.case_id: item for item in self.CORPUS}
        rating_by_id: dict[str, DanishBenchmarkRating] = {}
        for rating in ratings:
            if rating.case_id not in case_by_id:
                raise ValueError(f"unknown benchmark case: {rating.case_id}")
            if rating.case_id in rating_by_id:
                raise ValueError(f"duplicate benchmark case: {rating.case_id}")
            rating_by_id[rating.case_id] = rating

        if len(rating_by_id) < self.MINIMUM_CASES:
            raise ValueError(f"at least {self.MINIMUM_CASES} benchmark cases are required")

        critical_failures = tuple(
            case.case_id
            for case in self.CORPUS
            if case.critical
            and case.case_id in rating_by_id
            and min(
                rating_by_id[case.case_id].intelligibility,
                rating_by_id[case.case_id].pronunciation,
                rating_by_id[case.case_id].prosody,
                rating_by_id[case.case_id].stability,
            )
            < self.CRITICAL_MINIMUM
        )
        score = round(
            sum(rating.average for rating in rating_by_id.values())
            / (len(rating_by_id) * 5.0)
            * 100.0,
            2,
        )
        if critical_failures or score < self.CONDITIONAL_SCORE:
            status = "not_certified"
        elif score >= self.PASS_SCORE and evidence.state in {"documented", "runtime_dependent"}:
            status = "certified"
        else:
            status = "conditional"

        now = self._now_iso()
        provider_name = self.registry.manifest_for(normalized).display_name
        payload: dict[str, object] = {
            "document_schema_version": self.SCHEMA_VERSION,
            "provider_id": normalized,
            "provider_name": provider_name,
            "language_code": self.LANGUAGE_CODE,
            "status": status,
            "score": score,
            "case_count": len(rating_by_id),
            "minimum_cases": self.MINIMUM_CASES,
            "critical_failures": list(critical_failures),
            "voice_id": str(voice_id or "").strip(),
            "model_id": str(model_id or "").strip(),
            "reviewer": reviewer,
            "reviewed_at": now,
            "note": str(note or "").strip(),
            "documentation": evidence.to_dict(),
            "ratings": [rating_by_id[key].to_dict() for key in sorted(rating_by_id)],
            "safety_contract": {
                "automatic_synthesis": False,
                "automatic_provider_switch": False,
                "automatic_failover": False,
                "human_review_required": True,
            },
        }
        payload["payload_sha256"] = self._payload_digest(payload)
        timestamp = now.replace(":", "").replace("-", "")
        path = self.certifications_dir / f"{normalized}-{timestamp}.json"
        self._write_json(path, payload)
        latest = self.certifications_dir / f"latest-{normalized}.json"
        self._write_json(latest, payload)
        return self._certification_from_payload(payload, latest)

    def latest_certification(self, provider_id: str) -> DanishProviderCertification:
        normalized = str(provider_id or "unknown").strip().casefold() or "unknown"
        evidence = self.documentation_for(normalized)
        manifest = self.registry.manifest_for(normalized)
        if evidence.state == "test_only":
            return DanishProviderCertification(
                normalized,
                manifest.display_name,
                "not_applicable",
                evidence.state,
                None,
                0,
                self.MINIMUM_CASES,
                summary=evidence.note,
            )
        if evidence.state == "unsupported":
            return DanishProviderCertification(
                normalized,
                manifest.display_name,
                "not_certified",
                evidence.state,
                None,
                0,
                self.MINIMUM_CASES,
                summary=evidence.note,
            )

        path = self.certifications_dir / f"latest-{normalized}.json"
        payload = self._read_json(path)
        if payload is not None and self._verify_payload(payload):
            return self._certification_from_payload(payload, path)

        return DanishProviderCertification(
            normalized,
            manifest.display_name,
            "pending",
            evidence.state,
            None,
            0,
            self.MINIMUM_CASES,
            summary=(
                "Documented Danish support exists, but no verified human benchmark certification has been recorded."
                if evidence.state in {"documented", "runtime_dependent"}
                else evidence.note
            ),
        )

    def routing_language_state(self, provider_id: str, language_code: str | None) -> str:
        if self._base_language(language_code) != "da":
            return "unknown"
        return self.latest_certification(provider_id).routing_state

    def snapshot(self) -> DanishProviderBenchmarkSnapshot:
        providers = tuple(
            self.latest_certification(provider_id)
            for provider_id in self.registry.provider_ids()
        )
        return DanishProviderBenchmarkSnapshot(
            generated_at=self._now_iso(),
            language_code=self.LANGUAGE_CODE,
            minimum_cases=self.MINIMUM_CASES,
            pass_score=self.PASS_SCORE,
            providers=providers,
            cases=self.CORPUS,
        )

    def _certification_from_payload(
        self,
        payload: Mapping[str, object],
        path: Path,
    ) -> DanishProviderCertification:
        documentation = payload.get("documentation")
        documentation_state = (
            str(documentation.get("state") or "unknown")
            if isinstance(documentation, dict)
            else "unknown"
        )
        return DanishProviderCertification(
            provider_id=str(payload.get("provider_id") or "unknown"),
            provider_name=str(payload.get("provider_name") or "Unknown"),
            status=cast(DanishCertificationState, str(payload.get("status") or "pending")),
            documentation_state=cast(DanishDocumentationState, documentation_state),
            score=(float(payload["score"]) if payload.get("score") is not None else None),
            case_count=int(payload.get("case_count") or 0),
            minimum_cases=int(payload.get("minimum_cases") or self.MINIMUM_CASES),
            critical_failures=tuple(str(item) for item in (payload.get("critical_failures") or [])),
            voice_id=str(payload.get("voice_id") or ""),
            model_id=str(payload.get("model_id") or ""),
            reviewer=str(payload.get("reviewer") or ""),
            reviewed_at=str(payload.get("reviewed_at") or ""),
            evidence_path=str(path),
            evidence_sha256=self._sha256(path),
            summary=(
                f"Human-reviewed Danish benchmark: {float(payload.get('score') or 0):.1f}/100 across {int(payload.get('case_count') or 0)} cases."
            ),
        )

    @classmethod
    def _verify_payload(cls, payload: Mapping[str, object]) -> bool:
        digest = str(payload.get("payload_sha256") or "")
        if not digest:
            return False
        source = dict(payload)
        source.pop("payload_sha256", None)
        return digest == cls._payload_digest(source)

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, object] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""

    @staticmethod
    def _base_language(value: str | None) -> str:
        return str(value or "").strip().replace("_", "-").split("-", 1)[0].casefold()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
