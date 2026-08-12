from __future__ import annotations

from pathlib import Path

import pytest

from app.models import AppSettings
from app.models.api_profile import ApiProfile, ApiProfileStatus
from app.release import SCHEMA_VERSION
from app.services.provider_setup_wizard_service import ProviderSetupWizardService


class FakeProfiles:
    def __init__(self) -> None:
        self.profile = ApiProfile(
            profile_id="profile-1",
            display_name="Primary",
            provider="elevenlabs",
            enabled=True,
            active=True,
            has_saved_key=True,
            status=ApiProfileStatus.READY,
            remaining_characters=12345,
        )

    def list_profiles(self, provider: str | None = None):
        items = [self.profile]
        return [item for item in items if provider is None or item.provider == provider]

    def get_profile(self, profile_id: str):
        if profile_id != self.profile.profile_id:
            raise ValueError("API profile not found")
        return self.profile

    def apply_profile(self, settings, profile_id: str):
        profile = self.get_profile(profile_id)
        if profile.provider != settings.provider:
            raise ValueError("provider mismatch")
        return settings.model_copy(
            update={
                "active_api_profile_id": profile_id,
                "api_key": "secret-from-store",
            }
        )


class Controls:
    api_profile = True
    local_model_path = False
    voice_required = True


class Manifest:
    display_name = "ElevenLabs"
    locality = "cloud"
    credential_mode = "api_key"
    profile_management_ready = True
    profile_secret_required = True
    requires_credential = True
    controls = Controls()

    @staticmethod
    def profile_credential_ready(*, has_saved_secret: bool) -> bool:
        return has_saved_secret


class FakeProviders:
    def provider_ids(self):
        return ("elevenlabs", "mock")

    def manifest_for(self, provider_id: str):
        if provider_id == "elevenlabs":
            return Manifest()
        manifest = Manifest()
        manifest.display_name = "Mock"
        manifest.locality = "local"
        manifest.credential_mode = "none"
        manifest.profile_management_ready = False
        manifest.profile_secret_required = False
        manifest.requires_credential = False
        return manifest


class Source:
    state = "cached"
    message = "Cached account-scoped catalog."


class Item:
    def __init__(self, kind: str, item_id: str, name: str) -> None:
        self.kind = kind
        self.item_id = item_id
        self.name = name
        self.provider_id = "elevenlabs"
        self.languages = ("da",)
        self.source_state = "cached"


class Catalog:
    sources = (Source(),)
    items = (
        Item("voice", "voice-1", "Danish Voice"),
        Item("model", "model-1", "Danish Model"),
    )


class FakeCatalogService:
    def __init__(self) -> None:
        self.refresh_calls = []

    def snapshot_explicit_settings(self, provider_id, settings, *, allow_stale):
        assert provider_id == settings.provider
        assert allow_stale is True
        return Catalog()

    def refresh_provider_explicit_settings(self, provider_id, settings):
        self.refresh_calls.append((provider_id, settings.active_api_profile_id))
        return Source()


class Cost:
    estimated_cost = 0.5
    currency = "USD"
    source = "test"
    message = "Known test price"


class Quota:
    remaining = 12345
    message = "Confirmed quota"


class Limit:
    value = 5000
    unit = "characters"
    message = "Provider contract"


class Row:
    cost = Cost()
    quota = Quota()
    request_limit = Limit()


class FakeCostService:
    def provider_row(self, provider_id, settings, *, project_id, scoped_characters):
        assert provider_id == settings.provider
        assert scoped_characters >= 0
        return Row()


def service() -> ProviderSetupWizardService:
    return ProviderSetupWizardService(
        FakeProfiles(),
        FakeProviders(),
        FakeCatalogService(),
        FakeCostService(),
    )


def test_a3_database_schema_remains_23() -> None:
    assert SCHEMA_VERSION == 23


def test_a3_safety_contract_keeps_every_execution_authority_explicit() -> None:
    contract = ProviderSetupWizardService.safety_contract()
    assert contract["automatic_provider_switch"] is False
    assert contract["automatic_account_change"] is False
    assert contract["automatic_catalog_refresh"] is False
    assert contract["automatic_provider_probe"] is False
    assert contract["automatic_preflight_run"] is False
    assert contract["automatic_generation_start"] is False
    assert contract["automatic_generation_restart"] is False
    assert contract["automatic_cross_provider_failover"] is False
    assert contract["explicit_apply_required"] is True
    assert contract["explicit_refresh_required"] is True


def test_a3_provider_choices_are_static_manifest_composition() -> None:
    choices = service().provider_choices()
    assert tuple(item.provider_id for item in choices) == ("elevenlabs", "mock")
    assert choices[0].credential_mode == "api_key"
    assert choices[1].locality == "local"


def test_a3_draft_reads_cached_metadata_without_refreshing_provider() -> None:
    setup = service()
    draft = setup.build_draft(
        AppSettings(provider="elevenlabs", active_api_profile_id="profile-1"),
        provider_id="elevenlabs",
        profile_id="profile-1",
        voice_id="voice-1",
        model_id="model-1",
        language_code="da",
        scoped_characters=1000,
    )
    assert setup.catalog.refresh_calls == []
    assert draft.can_apply is True
    assert draft.selected_profile_name == "Primary"
    assert draft.settings.api_key == "secret-from-store"
    assert draft.catalog_state == "cached"
    assert draft.cost_text.startswith("Estimated provider cost")
    assert "12,345" in draft.quota_text
    assert "Text-to-Speech" in draft.capability_text
    assert "voice required" in draft.capability_text


def test_a3_cross_provider_choice_does_not_carry_cloud_secret_or_profile() -> None:
    setup = service()
    draft = setup.build_draft(
        AppSettings(
            provider="elevenlabs",
            api_key="do-not-carry",
            active_api_profile_id="profile-1",
            voice_id="old-voice",
            model_id="old-model",
        ),
        provider_id="mock",
        profile_id=None,
        voice_id="mock-voice",
        model_id="mock-model",
        language_code="da",
    )
    assert draft.settings.provider == "mock"
    assert draft.settings.api_key == ""
    assert draft.settings.active_api_profile_id is None



def test_a3_unified_catalog_exposes_explicit_account_context_api() -> None:
    source = Path("app/services/unified_voice_model_catalog_service.py").read_text(encoding="utf-8")
    assert "def snapshot_explicit_settings" in source
    assert "def refresh_provider_explicit_settings" in source
    method = source.split("def snapshot_explicit_settings", 1)[1].split("def refresh_provider_explicit_settings", 1)[0]
    assert "settings_for_provider(" not in method
    assert "active_profile(" not in method


def test_a3_refresh_contacts_provider_only_after_explicit_service_call() -> None:
    setup = service()
    base = AppSettings(provider="elevenlabs")
    assert setup.catalog.refresh_calls == []
    setup.refresh_provider_explicit(
        base,
        provider_id="elevenlabs",
        profile_id="profile-1",
    )
    assert setup.catalog.refresh_calls == [("elevenlabs", "profile-1")]


def test_a3_final_settings_rejects_cross_provider_account() -> None:
    setup = service()
    with pytest.raises(ValueError, match="belongs to"):
        setup.final_settings(
            AppSettings(provider="mock"),
            provider_id="mock",
            profile_id="profile-1",
            voice_id="voice",
            model_id="model",
            language_code="da",
        )


def test_a3_final_settings_requires_voice_for_voice_required_provider() -> None:
    setup = service()
    with pytest.raises(ValueError, match="voice is required"):
        setup.final_settings(
            AppSettings(provider="elevenlabs"),
            provider_id="elevenlabs",
            profile_id="profile-1",
            voice_id="",
            model_id="model-1",
            language_code="da",
        )


def test_a3_service_has_no_preflight_generation_or_smart_routing_calls() -> None:
    source = Path("app/services/provider_setup_wizard_service.py").read_text(encoding="utf-8")
    assert ".run_preflight(" not in source
    assert ".preflight(" not in source
    assert ".start(" not in source
    assert ".synthesize(" not in source
    assert "smart_provider_routing" not in source


def test_a3_dialog_does_not_refresh_or_apply_during_constructor() -> None:
    source = Path("app/gui/dialogs/provider_setup_wizard_dialog.py").read_text(encoding="utf-8")
    init_body = source.split("def __init__", 1)[1].split("def _build_pages", 1)[0]
    assert "refresh_provider_explicit" not in init_body
    assert "settings_selected.emit" not in init_body
    assert "Preflight" not in init_body


def test_a3_dialog_requires_explicit_confirmation_for_provider_contact_and_finish() -> None:
    source = Path("app/gui/dialogs/provider_setup_wizard_dialog.py").read_text(encoding="utf-8")
    assert "Refresh selected provider catalog?" in source
    assert "Apply provider setup choices?" in source
    assert "QMessageBox.Yes | QMessageBox.No" in source
    assert "settings_selected.emit(settings)" in source
    assert "Capabilities:" in source


def test_a3_main_window_wires_setup_without_running_preflight_or_generation() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def open_provider_setup_wizard", 1)[1].split("def apply_provider_setup_settings", 1)[0]
    assert "ProviderSetupWizardDialog" in method
    assert "settings_selected.connect(self.apply_provider_setup_settings)" in method
    assert "self.dry_run(" not in method
    assert "self.start(" not in method
    assert "self.apply_smart" not in method


def test_a3_explicit_apply_activates_selected_account_only_after_finish_signal() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def apply_provider_setup_settings", 1)[1].split("def show_shortcut_reference", 1)[0]
    assert "api_profile_service.set_active" in method
    assert "generation_controller.is_active" in method
    assert "settings_changed()" in method
    assert "invalidate_preflight()" in method
    assert "Preflight has NOT run" in method
    assert "generation has NOT started" in method
    assert "self.dry_run(" not in method
    assert "self.start(" not in method
    assert "self.apply_smart" not in method


def test_a3_help_settings_command_palette_and_onboarding_are_wired() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    onboarding = Path("app/services/first_run_onboarding_service.py").read_text(encoding="utf-8")
    assert "Provider Setup Wizard" in source
    assert "Settings: Provider Setup Wizard" in source
    assert "'provider_setup_wizard':self.open_provider_setup_wizard" in source
    assert '"provider_setup_wizard"' in onboarding
    assert '"Open Provider Setup Wizard"' in onboarding


def test_a3_keeps_a2_six_step_ids_and_persistence_contract() -> None:
    from app.services.first_run_onboarding_service import FirstRunOnboardingService

    assert FirstRunOnboardingService.step_ids() == (
        "workspace_orientation",
        "provider_readiness",
        "voice_model_choice",
        "project_sources",
        "preflight_approval",
        "generation_output",
    )
    assert FirstRunOnboardingService.DOCUMENT_SCHEMA_VERSION == 1


def test_a3_service_is_wired_through_container_and_application_context() -> None:
    container = Path("app/container.py").read_text(encoding="utf-8")
    bootstrap = Path("app/bootstrap.py").read_text(encoding="utf-8")
    assert "provider_setup_wizard_service: ProviderSetupWizardService" in container
    assert "provider_setup_wizard_service = ProviderSetupWizardService(" in container
    assert "provider_setup_wizard_service=provider_setup_wizard_service" in container
    assert "provider_setup_wizard_service: ProviderSetupWizardService" in bootstrap
    assert "provider_setup_wizard_service=services.provider_setup_wizard_service" in bootstrap


def test_a3_preserves_phase112_provider_ga_boundary_source() -> None:
    source = Path("app/services/provider_ga_certification_service.py").read_text(encoding="utf-8")
    assert "automatic_cross_provider_failover" in source
    assert '"human_release_promotion_required": True' in source
    assert "EXPECTED_BUILTIN_PROVIDER_IDS" in source


def test_a3_q2_stable_serial_profiled_gate_remains_default() -> None:
    gate = Path("scripts/quality-gate.ps1").read_text(encoding="utf-8-sig")
    profiler = Path("scripts/serial_pytest_profile.py").read_text(encoding="utf-8")
    assert "pytest (full / stable serial profiled)" in gate
    assert "scripts/serial_pytest_profile.py" in gate
    assert 'test_env.setdefault("S_TALKING_TEST_FAST_PATH", "1")' in profiler


def test_a3_documentation_declares_schema_and_authority_boundaries() -> None:
    docs = Path("docs/PROVIDER_SETUP_WIZARD_ROADMAP2_A3.md").read_text(encoding="utf-8")
    assert "Database schema remains **23**" in docs
    assert "hidden cross-provider failover" in docs
    assert "never calls Preflight" in docs
    assert "never starts generation" in docs
