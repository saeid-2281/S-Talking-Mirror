from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.runtime import RuntimeConfig
from app.models.danish_provider_benchmark import DanishBenchmarkRating
from app.release import SCHEMA_VERSION
from app.services.danish_provider_benchmark_service import DanishProviderBenchmarkService


def _runtime(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig.from_root(tmp_path)


def _service(tmp_path: Path) -> DanishProviderBenchmarkService:
    return DanishProviderBenchmarkService(_runtime(tmp_path))


def _ratings(score: int = 4) -> tuple[DanishBenchmarkRating, ...]:
    return tuple(
        DanishBenchmarkRating(case.case_id, score, score, score, score)
        for case in DanishProviderBenchmarkService.CORPUS
    )


def test_phase109_does_not_change_database_schema() -> None:
    assert SCHEMA_VERSION == 23


def test_phase109_fixed_corpus_is_deterministic_and_broad() -> None:
    cases = DanishProviderBenchmarkService.CORPUS
    assert len(cases) == 12
    assert len({case.case_id for case in cases}) == len(cases)
    assert sum(case.critical for case in cases) >= 6
    assert any("Arbejdsmiljørepræsentanten" in case.text for case in cases)
    assert any("Rødgrød" in case.text for case in cases)


def test_phase109_documented_support_is_not_quality_certification(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.documentation_for("openai").state == "documented"
    assert service.latest_certification("openai").status == "pending"
    assert service.latest_certification("openai").routing_state == "unknown"


def test_phase109_known_unsupported_danish_routes_remain_blocked(tmp_path: Path) -> None:
    service = _service(tmp_path)
    for provider_id in ("kokoro", "deepgram"):
        certification = service.latest_certification(provider_id)
        assert certification.status == "not_certified"
        assert certification.routing_state == "blocked"


def test_phase109_mock_is_not_a_production_certification_target(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.latest_certification("mock").status == "not_applicable"


def test_phase109_piper_is_runtime_and_voice_pack_specific(tmp_path: Path) -> None:
    service = _service(tmp_path)
    evidence = service.documentation_for("piper")
    assert evidence.state == "runtime_dependent"
    assert "MODEL_CARD" in evidence.note


def test_phase109_certification_requires_human_reviewer(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="reviewer"):
        service.save_evaluation(
            "cartesia",
            _ratings(),
            reviewer="",
            voice_id="voice",
            model_id="sonic-3.5",
        )


def test_phase109_certification_requires_minimum_case_count(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="at least"):
        service.save_evaluation(
            "cartesia",
            _ratings()[:5],
            reviewer="qa",
            voice_id="voice",
            model_id="sonic-3.5",
        )


def test_phase109_certifies_documented_provider_with_strong_human_scores(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.save_evaluation(
        "cartesia",
        _ratings(5),
        reviewer="Danish QA",
        voice_id="danish-voice",
        model_id="sonic-3.5",
    )
    assert result.status == "certified"
    assert result.score == 100.0
    assert result.routing_state == "confirmed"
    assert Path(result.evidence_path).is_file()
    assert result.evidence_sha256


def test_phase109_conditional_score_does_not_become_routing_confirmation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    ratings = list(_ratings(4))
    # 75/100 overall without a critical failure.
    ratings = [DanishBenchmarkRating(item.case_id, 4, 4, 4, 3) for item in ratings]
    result = service.save_evaluation(
        "resemble",
        ratings,
        reviewer="Danish QA",
        voice_id="voice",
        model_id="resemble-ultra",
    )
    assert result.status == "conditional"
    assert result.routing_state == "unknown"


def test_phase109_critical_failure_blocks_certification(tmp_path: Path) -> None:
    service = _service(tmp_path)
    ratings = list(_ratings(5))
    critical_id = next(case.case_id for case in service.CORPUS if case.critical)
    ratings = [
        DanishBenchmarkRating(item.case_id, 2, 5, 5, 5) if item.case_id == critical_id else item
        for item in ratings
    ]
    result = service.save_evaluation(
        "elevenlabs",
        ratings,
        reviewer="Danish QA",
        voice_id="voice",
        model_id="eleven_multilingual_v2",
    )
    assert result.status == "not_certified"
    assert critical_id in result.critical_failures


def test_phase109_unsupported_provider_cannot_be_overridden_by_manual_scores(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="cannot be certified"):
        service.save_evaluation(
            "deepgram",
            _ratings(5),
            reviewer="Danish QA",
            voice_id="voice",
            model_id="aura-2-thalia-en",
        )


def test_phase109_tampered_evidence_is_not_trusted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.save_evaluation(
        "openai",
        _ratings(5),
        reviewer="Danish QA",
        voice_id="coral",
        model_id="gpt-4o-mini-tts",
    )
    path = Path(result.evidence_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["score"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    current = service.latest_certification("openai")
    assert current.status == "pending"
    assert current.score is None


def test_phase109_exported_corpus_has_no_automatic_actions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    path = service.export_corpus()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["policy"]["automatic_synthesis"] is False
    assert payload["policy"]["automatic_provider_switch"] is False
    assert payload["policy"]["automatic_certification"] is False
    assert payload["policy"]["human_review_required"] is True


def test_phase109_non_danish_routing_is_unaffected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.routing_language_state("deepgram", "en-US") == "unknown"


def test_phase109_danish_routing_uses_only_verified_certification(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.routing_language_state("cartesia", "da-DK") == "unknown"
    service.save_evaluation(
        "cartesia",
        _ratings(5),
        reviewer="Danish QA",
        voice_id="voice",
        model_id="sonic-3.5",
    )
    assert service.routing_language_state("cartesia", "da-DK") == "confirmed"


def test_phase109_source_contract_contains_no_automatic_synthesis_or_switch() -> None:
    source = Path("app/services/danish_provider_benchmark_service.py").read_text(encoding="utf-8")
    assert "automatic_synthesis" in source
    assert "automatic_provider_switch" in source
    assert "human_review_required" in source
    assert "synthesize(" not in source


def test_phase109_pending_danish_certification_is_authoritative_over_cached_catalog() -> None:
    from types import SimpleNamespace

    from app.models.domain import AppSettings
    from app.models.unified_voice_model_catalog import UnifiedCatalogItem
    from app.services.smart_provider_routing_service import SmartProviderRoutingService

    class PendingDanishCertification:
        @staticmethod
        def routing_language_state(provider_id: str, language_code: str | None) -> str:
            del provider_id, language_code
            return "unknown"

    danish_voice = UnifiedCatalogItem(
        key="cartesia:voice:da",
        kind="voice",
        provider_id="cartesia",
        provider_name="Cartesia",
        profile_id=None,
        profile_name=None,
        item_id="danish-voice",
        name="Danish Voice",
        languages=("da-DK",),
    )
    danish_model = UnifiedCatalogItem(
        key="cartesia:model:sonic-3.5",
        kind="model",
        provider_id="cartesia",
        provider_name="Cartesia",
        profile_id=None,
        profile_name=None,
        item_id="sonic-3.5",
        name="Sonic 3.5",
        languages=("da",),
    )

    class CachedCatalog:
        @staticmethod
        def snapshot(settings, *, provider_ids, allow_stale):
            del settings, provider_ids, allow_stale
            return SimpleNamespace(items=(danish_voice, danish_model))

    service = object.__new__(SmartProviderRoutingService)
    service.danish_provider_benchmark_service = PendingDanishCertification()
    service.unified_catalog_service = CachedCatalog()

    settings = AppSettings(provider="mock", language_code="da")
    provider_settings = AppSettings(provider="cartesia", language_code="da")
    language_state, voice_state, model_state, voice_id, model_id = service._catalog_evidence(
        "cartesia",
        settings=settings,
        provider_settings=provider_settings,
        readiness_detail="",
        current_provider="mock",
    )

    assert language_state == "unknown"
    assert voice_state == "confirmed"
    assert model_state == "confirmed"
    assert voice_id == "danish-voice"
    assert model_id == "sonic-3.5"


def test_phase109_not_explicit_documentation_cannot_become_fully_certified(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.save_evaluation(
        "murf",
        _ratings(5),
        reviewer="Danish QA",
        voice_id="voice",
        model_id="GEN2",
    )
    assert result.status == "conditional"
    assert result.routing_state == "unknown"
