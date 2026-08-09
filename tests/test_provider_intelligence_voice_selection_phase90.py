from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.provider_intelligence import ProviderIntelligenceCard
from app.models.api_profile import ApiProfile
from app.models.domain import AppSettings
from app.models.provider_contract import ProviderCapabilities
from app.models.provider_identity import ProviderReadiness
from app.models.provider_intelligence import (
    ProviderIntelligenceState,
    ProviderSelectionSuggestion,
)
from app.services.provider_intelligence_service import ProviderIntelligenceService
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem


class _Readiness:
    def __init__(self, *, state: str = "Ready", reason: str = "Ready") -> None:
        self.state = state
        self.reason = reason

    def readiness_for(self, provider_id: str, settings: AppSettings) -> ProviderReadiness:
        blocking = self.state in {
            "Setup required",
            "Dependency missing",
            "Partial implementation",
            "Not production-ready",
        }
        return ProviderReadiness(
            provider_id=provider_id,
            display_name=provider_id.title(),
            state=self.state,
            reason=self.reason,
            adapter_registered=not blocking,
            dependency_installed=not blocking,
            credential_setup_available=True,
            model_listing_implemented=True,
            voice_listing_implemented=True,
            language_handling_implemented=True,
            synthesis_implemented=not blocking,
            output_format_supported=True,
            cancellation_implemented=True,
            atomic_output_implemented=True,
            retry_implemented=True,
            error_normalization_implemented=True,
            preflight_integration_implemented=True,
            gui_settings_implemented=True,
        )


class _CatalogService:
    def __init__(self, *, voices: bool = True, models: bool = True, quota: bool = True) -> None:
        self.voices = voices
        self.models = models
        self.quota = quota

    def capabilities_for(self, provider_id: str, settings: AppSettings) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=provider_id,
            display_name=provider_id.title(),
            remote=provider_id not in {"mock", "piper", "kokoro"},
            requires_credential=provider_id not in {"mock", "piper", "kokoro"},
            supports_voice_listing=self.voices,
            supports_model_listing=self.models,
            supports_language_code=True,
            supports_quota_lookup=self.quota,
            supported_output_formats=("mp3",),
        )


class _VoiceService:
    def __init__(self, catalog: VoiceCatalog | None) -> None:
        self.catalog = catalog

    def cached_catalog(self, settings: AppSettings) -> VoiceCatalog | None:
        return self.catalog


class _Cost:
    def estimate_cost(self, **_kwargs):
        return 0.0125, 25.0, "USD", "phase90-test"


def _catalog(*, remaining: int = 50_000) -> VoiceCatalog:
    return VoiceCatalog(
        voices=(
            VoiceItem(
                provider="elevenlabs",
                voice_id="voice-en",
                name="English Voice",
                language="en",
                category="professional",
                description="",
                labels={},
                is_favorite=False,
                compatible_model_ids=("model-en",),
            ),
            VoiceItem(
                provider="elevenlabs",
                voice_id="voice-da",
                name="Danish Favorite",
                language="da",
                category="professional",
                description="",
                labels={},
                is_favorite=True,
                compatible_model_ids=("model-da",),
            ),
        ),
        models=(
            VoiceModelItem("model-en", "English Model", ("en",)),
            VoiceModelItem("model-da", "Danish Model", ("da",)),
        ),
        account=AccountUsage(
            tier="creator",
            status="active",
            character_count=100_000 - remaining,
            character_limit=100_000,
        ),
        refreshed_at="2026-08-09T10:00:00+00:00",
    )


def _service(
    catalog: VoiceCatalog | None,
    *,
    readiness_state: str = "Ready",
    readiness_reason: str = "Ready",
    voices: bool = True,
) -> ProviderIntelligenceService:
    return ProviderIntelligenceService(
        _Readiness(state=readiness_state, reason=readiness_reason),
        _CatalogService(voices=voices),
        _VoiceService(catalog),
        _Cost(),
    )


def test_phase90_compatible_selection_surfaces_quota_cost_and_preflight_action() -> None:
    service = _service(_catalog())
    state = service.analyze(
        settings=AppSettings(
            provider="elevenlabs",
            api_key="test",
            model_id="model-da",
            voice_id="voice-da",
            language_code="da",
        ),
        scoped_jobs=12,
        scoped_characters=5_000,
        project_id=7,
        connection_status="Connected: ready",
    )

    assert state.status == "Connected"
    assert state.compatibility_tone == "success"
    assert "Danish Model" in state.compatibility_text
    assert "50,000" in state.quota_text
    assert state.cost_text.startswith("USD 0.0125")
    assert state.primary_action_code == "preflight"


def test_phase90_model_language_mismatch_recommends_compatible_model_and_voice() -> None:
    service = _service(_catalog())
    state = service.analyze(
        settings=AppSettings(
            provider="elevenlabs",
            api_key="test",
            model_id="model-en",
            voice_id="voice-en",
            language_code="da",
        ),
        scoped_jobs=2,
        scoped_characters=500,
        project_id=None,
    )

    assert state.primary_action_code == "apply-suggestion"
    assert state.suggestion.model_id == "model-da"
    assert state.suggestion.voice_id == "voice-da"
    assert "model/language mismatch" in state.compatibility_text


def test_phase90_missing_voice_uses_favorite_compatible_voice() -> None:
    service = _service(_catalog())
    state = service.analyze(
        settings=AppSettings(
            provider="elevenlabs",
            api_key="test",
            model_id="model-da",
            voice_id="",
            language_code="da",
        ),
        scoped_jobs=1,
        scoped_characters=100,
        project_id=None,
    )

    assert state.suggestion.voice_id == "voice-da"
    assert state.suggestion.voice_name == "Danish Favorite"
    assert state.primary_action_code == "apply-suggestion"


def test_phase90_quota_shortfall_recommends_existing_quota_scope() -> None:
    service = _service(_catalog(remaining=1_000))
    state = service.analyze(
        settings=AppSettings(
            provider="elevenlabs",
            api_key="test",
            model_id="model-da",
            voice_id="voice-da",
            language_code="da",
        ),
        scoped_jobs=10,
        scoped_characters=2_500,
        project_id=None,
    )

    assert state.status == "Quota blocked"
    assert state.quota_tone == "error"
    assert "short by 1,500" in state.quota_text
    assert state.primary_action_code == "quota-scope"


def test_phase90_missing_catalog_requests_refresh_without_live_probe() -> None:
    service = _service(None)
    state = service.analyze(
        settings=AppSettings(
            provider="elevenlabs",
            api_key="test",
            model_id="model-da",
            voice_id="voice-da",
            language_code="da",
        ),
        scoped_jobs=3,
        scoped_characters=700,
        project_id=None,
    )

    assert state.catalog_available is False
    assert state.primary_action_code == "refresh-catalog"
    assert "refresh" in state.recommendation.casefold()


def test_phase90_readiness_blocker_keeps_provider_review_authoritative() -> None:
    service = _service(
        _catalog(),
        readiness_state="Setup required",
        readiness_reason="Credential profile is required.",
    )
    state = service.analyze(
        settings=AppSettings(provider="elevenlabs", model_id="model-da", voice_id="voice-da"),
        scoped_jobs=3,
        scoped_characters=700,
        project_id=None,
    )

    assert state.tone == "error"
    assert state.primary_action_code == "provider"
    assert "Credential" in state.recommendation


def test_phase90_local_provider_does_not_require_explicit_voice() -> None:
    service = _service(None, voices=False)
    state = service.analyze(
        settings=AppSettings(provider="mock", model_id="piper-local", voice_id=""),
        scoped_jobs=1,
        scoped_characters=50,
        project_id=None,
        connection_status="Ready",
    )

    assert "voice required" not in state.compatibility_text.casefold()
    assert state.primary_action_code == "preflight"


def test_phase90_confirmed_profile_quota_overrides_catalog_account() -> None:
    service = _service(_catalog(remaining=50_000))
    profile = ApiProfile(
        profile_id="profile-1",
        display_name="Primary",
        provider="elevenlabs",
        remaining_characters=4_000,
        character_limit=10_000,
    )
    state = service.analyze(
        settings=AppSettings(
            provider="elevenlabs",
            api_key="test",
            model_id="model-da",
            voice_id="voice-da",
            language_code="da",
        ),
        scoped_jobs=2,
        scoped_characters=500,
        project_id=None,
        profile=profile,
    )

    assert "4,000 / 10,000" in state.quota_text


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def _ui_state(*, action: str = "preflight") -> ProviderIntelligenceState:
    suggestion = ProviderSelectionSuggestion(
        model_id="model-da" if action == "apply-suggestion" else None,
        model_name="Danish Model" if action == "apply-suggestion" else None,
        voice_id="voice-da" if action == "apply-suggestion" else None,
        voice_name="Danish Voice" if action == "apply-suggestion" else None,
    )
    return ProviderIntelligenceState(
        provider_id="elevenlabs",
        provider_name="ElevenLabs",
        status="Connected",
        tone="success",
        selection_summary="Danish Model · Danish Voice",
        compatibility_text="Compatible",
        compatibility_tone="success",
        quota_text="20,000 remaining",
        quota_tone="success",
        batch_text="4 jobs · 1,000 characters",
        cost_text="USD 0.0250",
        recommendation="Ready for preflight.",
        primary_action_code=action,
        primary_action_label="Apply suggestion" if action == "apply-suggestion" else "Run preflight",
        suggestion=suggestion,
        catalog_available=True,
        scoped_jobs=4,
        scoped_characters=1_000,
    )


def test_phase90_intelligence_card_renders_decision_and_emits_action(qt_app) -> None:
    card = ProviderIntelligenceCard()
    state = _ui_state(action="apply-suggestion")
    emitted: list[str] = []
    card.actionRequested.connect(emitted.append)
    card.set_state(state)
    card.show()
    qt_app.processEvents()

    assert card.objectName() == "providerIntelligenceCard"
    assert card.status_badge.text() == "Connected"
    assert "20,000" in card.quota_label.text()
    assert card.primary_action.text() == "Apply suggestion"
    card.primary_action.click()
    assert emitted == ["apply-suggestion"]


def test_phase90_main_exposes_provider_intelligence_and_shortcut(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert isinstance(window.provider_intelligence, ProviderIntelligenceCard)
    assert window.provider_intelligence_service is window.context.provider_intelligence_service
    assert window.actions_by_name["Provider Intelligence"].shortcut().toString() == "Ctrl+Alt+V"
    commands = [item.name for item in window.command_palette_commands()]
    assert "Provider: Intelligence & Selection" in commands


def test_phase90_apply_suggestion_changes_only_model_and_voice(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()
    window.provider.setCurrentText("mock")
    provider_before = window.provider.currentText()
    window._provider_intelligence_state = _ui_state(action="apply-suggestion")

    window.apply_provider_intelligence_suggestion()
    qt_app.processEvents()

    assert window.provider.currentText() == provider_before
    assert window.current_model_id() == "model-da"
    assert window.voice.text() == "voice-da"


def test_phase90_quota_action_reuses_existing_quota_batch_scope(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.handle_provider_intelligence_action("quota-scope")
    qt_app.processEvents()

    assert window.scope_selector.currentData() == "quota_batch"


def test_phase90_theme_styles_intelligence_tones() -> None:
    source = Path("app/gui/theme.py").read_text(encoding="utf-8")
    assert "QFrame#providerIntelligenceCard" in source
    assert 'QLabel#providerOverviewValue[tone="success"]' in source
    assert 'QLabel#providerOverviewValue[tone="warning"]' in source
    assert 'QLabel#providerOverviewValue[tone="error"]' in source
