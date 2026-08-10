from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.gui.main import MainWindow
from app.gui.widgets.smart_provider_routing import SmartProviderRoutingCard
from app.models.api_profile import ApiProfile
from app.models.domain import AppSettings
from app.models.offline_tts_engine import OfflineEngineSnapshot, OfflineVoiceDescriptor
from app.models.provider_identity import ProviderReadiness
from app.models.smart_provider_routing import ProviderRouteCandidate, SmartProviderRoutingState
from app.services.smart_provider_routing_service import SmartProviderRoutingService


class _Readiness:
    def __init__(self, *, state: str = "Ready", reason: str = "Configured provider ready") -> None:
        self.state = state
        self.reason = reason

    def readiness_for(self, provider_id: str, settings: AppSettings) -> ProviderReadiness:
        return ProviderReadiness(
            provider_id=provider_id,
            display_name="ElevenLabs" if provider_id == "elevenlabs" else provider_id.title(),
            state=self.state,
            reason=self.reason,
            adapter_registered=True,
            dependency_installed=True,
            credential_setup_available=True,
            model_listing_implemented=True,
            voice_listing_implemented=True,
            language_handling_implemented=True,
            synthesis_implemented=True,
            output_format_supported=True,
            cancellation_implemented=True,
            atomic_output_implemented=True,
            retry_implemented=True,
            error_normalization_implemented=True,
            preflight_integration_implemented=True,
            gui_settings_implemented=True,
        )


class _Offline:
    def __init__(self, *, ready: bool = True, model_path: str = "C:/voices/da.onnx") -> None:
        self.ready = ready
        self.model_path = model_path

    def snapshot(self, engine_id: str, settings: AppSettings) -> OfflineEngineSnapshot:
        assert engine_id == "piper"
        voice = OfflineVoiceDescriptor(
            engine_id="piper",
            voice_id=Path(self.model_path).stem,
            display_name="Danish Piper",
            model_path=self.model_path,
            config_path=f"{self.model_path}.json",
            language_code="da",
            config_present=True,
            selected=True,
        )
        return OfflineEngineSnapshot(
            engine_id="piper",
            display_name="Piper",
            provider_id="piper",
            dependency_name="piper",
            installed=self.ready,
            module_available=self.ready,
            executable_path=None,
            runtime_mode="python-api" if self.ready else "unavailable",
            configured=self.ready,
            ready=self.ready,
            selected_voice_id=voice.voice_id if self.ready else None,
            voices=(voice,) if self.ready else (),
            accelerators=("CPU", "CUDA optional"),
            state="Runtime warm" if self.ready else "Setup required",
            summary="Piper is ready." if self.ready else "Piper needs setup.",
        )


class _Cost:
    def __init__(self, estimate: float = 0.05, *, rate: float = 25.0, source: str = "test-rate") -> None:
        self.estimate = estimate
        self.rate = rate
        self.source = source

    def estimate_cost(self, **_kwargs):
        return self.estimate, self.rate, "USD", self.source


def _service(*, piper_ready: bool = True, current_state: str = "Ready", cost: _Cost | None = None):
    return SmartProviderRoutingService(
        _Readiness(state=current_state),
        _Offline(ready=piper_ready),
        cost,
    )


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="test",
        model_id="eleven_multilingual_v2",
        voice_id="voice-da",
        language_code="da",
        piper_model_path="C:/voices/da.onnx",
    )
    return base.model_copy(update=updates)


def test_phase98_balanced_keeps_ready_cloud_and_surfaces_piper_fallback() -> None:
    state = _service(cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=5,
        scoped_characters=2_000,
        project_id=1,
        preference="balanced",
    )

    assert state.recommended_provider_id == "elevenlabs"
    assert state.switch_required is False
    assert state.piper_candidate.ready is True
    assert "offline fallback" in state.recommendation
    assert state.no_automatic_failover is True


def test_phase98_privacy_first_recommends_ready_piper() -> None:
    state = _service(cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=5,
        scoped_characters=2_000,
        project_id=None,
        preference="privacy",
    )

    assert state.recommends_piper
    assert state.action_label == "Use Piper offline"
    assert state.action_enabled is True
    assert "Privacy-first" in state.recommendation


def test_phase98_confirmed_quota_shortfall_recommends_piper() -> None:
    profile = ApiProfile(
        profile_id="primary",
        display_name="Primary",
        provider="elevenlabs",
        remaining_characters=1_000,
        character_limit=20_000,
    )
    state = _service(cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=10,
        scoped_characters=2_500,
        project_id=None,
        current_profile=profile,
        preference="cloud_first",
    )

    assert state.current_candidate.quota_shortfall == 1_500
    assert state.recommends_piper
    assert "short by 1,500" in state.recommendation


def test_phase98_blocked_cloud_readiness_recommends_piper() -> None:
    state = _service(current_state="Setup required", cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=2,
        scoped_characters=300,
        project_id=None,
    )

    assert state.current_candidate.ready is False
    assert state.recommends_piper


def test_phase98_connection_failure_can_trigger_explicit_offline_fallback() -> None:
    state = _service(cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=2,
        scoped_characters=300,
        project_id=None,
        connection_status="Connection failed: timeout",
    )

    assert state.current_candidate.ready is False
    assert state.recommends_piper


def test_phase98_lowest_cost_uses_confirmed_cloud_cost_only() -> None:
    state = _service(cost=_Cost(0.25)).analyze(
        settings=_settings(),
        scoped_jobs=20,
        scoped_characters=10_000,
        project_id=4,
        preference="lowest_cost",
    )

    assert state.recommends_piper
    assert state.piper_candidate.cost_text == "No provider fee"
    assert "USD 0.2500" in state.recommendation


def test_phase98_unknown_cloud_pricing_does_not_force_switch() -> None:
    state = _service(cost=None).analyze(
        settings=_settings(),
        scoped_jobs=3,
        scoped_characters=900,
        project_id=None,
        preference="lowest_cost",
    )

    assert state.recommended_provider_id == "elevenlabs"
    assert state.switch_required is False
    assert "pricing is not confirmed" in state.recommendation


def test_phase98_unavailable_piper_never_becomes_recommended_route() -> None:
    state = _service(piper_ready=False, cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=3,
        scoped_characters=900,
        project_id=None,
        preference="privacy",
    )

    assert state.recommended_provider_id == "elevenlabs"
    assert state.piper_candidate.ready is False
    assert state.action_enabled is False


def test_phase98_active_generation_disables_explicit_switch() -> None:
    state = _service(cost=_Cost()).analyze(
        settings=_settings(),
        scoped_jobs=4,
        scoped_characters=1_500,
        project_id=None,
        preference="privacy",
        generation_active=True,
    )

    assert state.recommends_piper
    assert state.action_enabled is False


def test_phase98_piper_current_route_never_infers_hidden_cloud_restore() -> None:
    service = SmartProviderRoutingService(
        _Readiness(state="Ready"),
        _Offline(ready=True),
        _Cost(),
    )
    state = service.analyze(
        settings=_settings(provider="piper", model_id="piper-local", voice_id="da"),
        scoped_jobs=2,
        scoped_characters=400,
        project_id=None,
        preference="cloud_first",
    )

    assert state.recommended_provider_id == "piper"
    assert state.switch_required is False
    assert "already selected" in state.recommendation


def _route_state(model_path: str) -> SmartProviderRoutingState:
    current = ProviderRouteCandidate(
        provider_id="elevenlabs",
        provider_name="ElevenLabs",
        locality="cloud",
        ready=True,
        status="Ready",
        detail="Ready",
        estimated_cost=0.05,
        currency="USD",
    )
    piper = ProviderRouteCandidate(
        provider_id="piper",
        provider_name="Piper",
        locality="local",
        ready=True,
        status="Runtime warm",
        detail="Ready",
        estimated_cost=0.0,
        selected_voice_id=Path(model_path).stem,
        selected_model_path=model_path,
    )
    return SmartProviderRoutingState(
        preference="privacy",
        current_provider_id="elevenlabs",
        current_provider_name="ElevenLabs",
        recommended_provider_id="piper",
        recommended_provider_name="Piper",
        route_summary="ElevenLabs → Piper",
        recommendation="Privacy-first routing prefers Piper.",
        tone="warning",
        switch_required=True,
        action_label="Use Piper offline",
        action_enabled=True,
        current_candidate=current,
        piper_candidate=piper,
        scoped_jobs=2,
        scoped_characters=400,
    )


def test_phase98_routing_card_renders_preference_and_emits_explicit_actions(qt_app) -> None:
    card = SmartProviderRoutingCard()
    emitted: list[str] = []
    preferences: list[str] = []
    card.actionRequested.connect(emitted.append)
    card.preferenceChanged.connect(preferences.append)
    card.set_state(_route_state("C:/voices/da.onnx"))
    card.show()
    qt_app.processEvents()

    assert "ElevenLabs" in card.route_label.text()
    assert card.primary_action.text() == "Use Piper offline"
    card.primary_action.click()
    assert emitted == ["apply"]
    card.preference.setCurrentIndex(card.preference.findData("lowest_cost"))
    assert preferences[-1] == "lowest_cost"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase98_di_and_main_expose_routing_card_shortcut_and_palette(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert isinstance(window.smart_provider_routing, SmartProviderRoutingCard)
    assert window.smart_provider_routing_service is window.context.smart_provider_routing_service
    assert window.actions_by_name["Smart Provider Routing"].shortcut().toString() == "Ctrl+Alt+S"
    assert "Provider: Smart Routing" in [item.name for item in window.command_palette_commands()]


def test_phase98_apply_recommendation_reuses_existing_piper_voice_path_without_start(qt_app, tmp_path: Path) -> None:
    model = tmp_path / "da_DK-test-medium.onnx"
    model.write_bytes(b"onnx")
    Path(f"{model}.json").write_text("{}", encoding="utf-8")
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()
    window.provider.setCurrentText("elevenlabs")
    started: list[bool] = []
    window.start = lambda: started.append(True)

    state = _route_state(str(model))

    class _Router:
        @staticmethod
        def normalize_preference(value: str) -> str:
            return value or "privacy"

        def analyze(self, **_kwargs):
            return state

    window.smart_provider_routing_service = _Router()
    window._smart_provider_routing_signature = None

    assert window.apply_smart_provider_routing_recommendation() is True
    qt_app.processEvents()

    assert window.provider.currentText() == "piper"
    assert window.current_model_id() == "piper-local"
    assert window.voice.text() == model.stem
    assert window.piper.text() == str(model)
    assert started == []


def test_phase98_database_schema_23_is_preserved(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase98.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23


def test_phase98_contract_contains_no_automatic_cross_provider_generation() -> None:
    service_source = Path("app/services/smart_provider_routing_service.py").read_text(encoding="utf-8")
    main_source = Path("app/gui/main.py").read_text(encoding="utf-8")
    docs = Path("docs/SMART_PROVIDER_ROUTING_PHASE98.md").read_text(encoding="utf-8")

    assert "network" in service_source
    assert "apply_offline_piper_voice(model_path)" in main_source
    assert "self.start()" not in main_source[main_source.index("def apply_smart_provider_routing_recommendation"):main_source.index("def focus_smart_provider_routing")]
    assert "automatic retry on another provider" in docs
    assert "Cloud → Piper switching during a run" in docs
