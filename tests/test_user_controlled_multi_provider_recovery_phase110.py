from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.domain import AppSettings, JobStatus, TTSJob
from app.models.smart_provider_routing import ProviderRouteCandidate, SmartProviderRoutingState
from app.release import SCHEMA_VERSION
from app.services.user_controlled_provider_recovery_service import (
    UserControlledProviderRecoveryService,
)


class FakeProviders:
    names = {
        "elevenlabs": "ElevenLabs",
        "cartesia": "Cartesia",
        "piper": "Piper",
        "mock": "Mock",
    }

    def manifest_for(self, provider_id: str):
        return SimpleNamespace(display_name=self.names.get(provider_id, provider_id))


class FakeRouting:
    def __init__(self) -> None:
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        current = ProviderRouteCandidate(
            provider_id="elevenlabs",
            provider_name="ElevenLabs",
            locality="cloud",
            ready=False,
            eligible=False,
            status="Blocked",
            detail="Provider request failed",
            score=30,
            rank=3,
            blockers=("Current provider failed.",),
        )
        cartesia = ProviderRouteCandidate(
            provider_id="cartesia",
            provider_name="Cartesia",
            locality="cloud",
            ready=True,
            eligible=True,
            status="Ready",
            detail="Danish route ready",
            score=91,
            rank=1,
            language_state="confirmed",
            voice_state="confirmed",
            model_state="confirmed",
            account_state="ready",
            request_limit_state="confirmed",
            profile_id="cartesia-profile",
            profile_name="Cartesia primary",
            recommended_voice_id="da-voice",
            recommended_model_id="sonic-3.5",
        )
        piper = ProviderRouteCandidate(
            provider_id="piper",
            provider_name="Piper",
            locality="local",
            ready=True,
            eligible=True,
            status="Ready",
            detail="Verified local voice",
            score=80,
            rank=2,
            language_state="confirmed",
            voice_state="confirmed",
            model_state="confirmed",
            account_state="not_applicable",
            request_limit_state="not_applicable",
        )
        mock = ProviderRouteCandidate(
            provider_id="mock",
            provider_name="Mock",
            locality="local",
            ready=True,
            eligible=True,
            status="Ready",
            detail="test only",
            score=99,
            rank=0,
        )
        return SmartProviderRoutingState(
            preference="reliability",
            current_provider_id="elevenlabs",
            current_provider_name="ElevenLabs",
            recommended_provider_id="cartesia",
            recommended_provider_name="Cartesia",
            route_summary="ElevenLabs → Cartesia",
            recommendation="Review Cartesia",
            tone="warning",
            switch_required=True,
            action_label="Review Cartesia",
            action_enabled=True,
            current_candidate=current,
            piper_candidate=piper,
            scoped_jobs=kwargs["scoped_jobs"],
            scoped_characters=kwargs["scoped_characters"],
            candidates=(mock, cartesia, piper, current),
        )


def _service(tmp_path: Path) -> tuple[UserControlledProviderRecoveryService, FakeRouting]:
    routing = FakeRouting()
    return UserControlledProviderRecoveryService(tmp_path, routing, FakeProviders()), routing


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, text="Hej verden", filename="one", status=JobStatus.FAILED),
        TTSJob(row_number=2, text="Dansk tekst", filename="two", status=JobStatus.PENDING),
        TTSJob(row_number=3, text="Færdig", filename="three", status=JobStatus.COMPLETED),
    ]


def test_phase110_does_not_change_database_schema() -> None:
    assert SCHEMA_VERSION == 23


def test_phase110_assessment_is_recovery_scope_only(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"),
        jobs=_jobs(),
        project_id=7,
        failure_message="network failed",
    )
    assert assessment.failed_rows == (1,)
    assert assessment.pending_rows == (2,)
    assert assessment.recoverable_rows == (1, 2)
    assert assessment.scoped_jobs == 2
    assert assessment.scoped_characters == len("Hej verden") + len("Dansk tekst")


def test_phase110_excludes_current_and_mock_from_alternates(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    assert [item.provider_id for item in assessment.candidates] == ["cartesia", "piper"]
    assert assessment.recommended_provider_id == "cartesia"


def test_phase110_assessment_is_cached_configured_only(tmp_path: Path) -> None:
    service, routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    assert assessment.network_refresh_performed is False
    assert assessment.automatic_provider_switch is False
    assert assessment.automatic_generation_restart is False
    assert routing.calls[0]["generation_active"] is False
    assert routing.calls[0]["preference"] == "reliability"


def test_phase110_failure_summary_redacts_secret_like_material(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"),
        jobs=_jobs(),
        project_id=None,
        failure_message="Bearer abc.def api_key=super-secret network failed",
    )
    assert "abc.def" not in assessment.failure_summary
    assert "super-secret" not in assessment.failure_summary
    assert "[REDACTED]" in assessment.failure_summary


def test_phase110_prepare_requires_explicit_approval(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    with pytest.raises(ValueError, match="Explicit user approval"):
        service.prepare_receipt(
            assessment,
            selected_settings=AppSettings(
                provider="cartesia", model_id="sonic-3.5", voice_id="da-voice"
            ),
            approved=False,
        )


def test_phase110_prepare_requires_alternate_provider(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    with pytest.raises(ValueError, match="alternate provider"):
        service.prepare_receipt(
            assessment,
            selected_settings=AppSettings(provider="elevenlabs"),
            approved=True,
        )


def test_phase110_prepare_rejects_unreviewed_provider(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    with pytest.raises(ValueError, match="reviewed recovery assessment"):
        service.prepare_receipt(
            assessment,
            selected_settings=AppSettings(
                provider="openai", model_id="gpt-4o-mini-tts", voice_id="coral"
            ),
            approved=True,
        )


def test_phase110_piper_requires_explicit_voice_pack(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    with pytest.raises(ValueError, match="voice pack"):
        service.prepare_receipt(
            assessment,
            selected_settings=AppSettings(provider="piper", model_id="piper-local"),
            approved=True,
        )


def test_phase110_receipt_is_tamper_evident_and_secret_free(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    selected = AppSettings(
        provider="cartesia",
        api_key="secret-key-must-not-be-written",
        active_api_profile_id="cartesia-profile",
        model_id="sonic-3.5",
        voice_id="da-voice",
    )
    receipt = service.prepare_receipt(assessment, selected_settings=selected, approved=True)
    assert service.verify_receipt(receipt)
    payload = json.loads(Path(receipt.path).read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert "secret-key-must-not-be-written" not in serialized
    assert payload["policy"]["automatic_provider_switch"] is False
    assert payload["policy"]["automatic_generation_restart"] is False
    assert payload["policy"]["preflight_required"] is True
    assert payload["policy"]["explicit_start_required"] is True
    payload["to_provider_id"] = "piper"
    Path(receipt.path).write_text(json.dumps(payload), encoding="utf-8")
    assert service.verify_receipt(receipt) is False


def test_phase110_receipt_never_marks_generation_started(tmp_path: Path) -> None:
    service, _routing = _service(tmp_path)
    assessment = service.assess(
        settings=AppSettings(provider="elevenlabs"), jobs=_jobs(), project_id=None
    )
    receipt = service.prepare_receipt(
        assessment,
        selected_settings=AppSettings(
            provider="cartesia", model_id="sonic-3.5", voice_id="da-voice"
        ),
        approved=True,
    )
    assert receipt.generation_started is False


def test_phase110_source_contract_contains_no_cross_provider_execution() -> None:
    source = Path("app/services/user_controlled_provider_recovery_service.py").read_text(
        encoding="utf-8"
    )
    assert "does not refresh catalogs" in source
    assert "synthesize(" not in source
    assert "create_provider(" not in source
    assert ".start(" not in source


def test_phase110_generation_worker_is_not_modified_for_cross_provider_recovery() -> None:
    worker = Path("app/gui/worker.py").read_text(encoding="utf-8")
    assert "UserControlledProviderRecoveryService" not in worker
    assert "cross_provider_recovery" not in worker


def test_phase110_main_requires_preflight_and_manual_start_after_prepare() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "def prepare_user_controlled_provider_recovery" in source
    method = source.split("def prepare_user_controlled_provider_recovery", 1)[1].split(
        "def ", 1
    )[0]
    assert "run_preflight" in method
    assert "self.start()" not in method
    assert "retry_failed" in method


def test_phase110_documentation_preserves_architectural_law() -> None:
    docs = Path("docs/USER_CONTROLLED_MULTI_PROVIDER_RECOVERY_PHASE110.md").read_text(
        encoding="utf-8"
    )
    assert "No automatic cross-provider switch" in docs
    assert "Preflight validates" in docs
    assert "User decides" in docs
    assert "Generation Engine executes" in docs
