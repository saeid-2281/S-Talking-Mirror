from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import AppSettings
from app.models.provider_plugin import PLUGIN_SDK_API_VERSION
from app.provider_factory import available_provider_ids, create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from app.services.provider_identity_service import ProviderIdentityService
from app.services.provider_plugin_sdk_service import ProviderPluginSDKService


def _base_registry() -> ProviderRegistry:
    return ProviderRegistry(
        tuple(
            DEFAULT_PROVIDER_REGISTRY.manifest_for(provider_id)
            for provider_id in DEFAULT_PROVIDER_REGISTRY.provider_ids()
        )
    )


def _plugin(
    root: Path,
    provider_id: str = "sample_tts",
    *,
    code: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "sdk_api_version": PLUGIN_SDK_API_VERSION,
        "plugin_id": f"{provider_id}.provider",
        "provider_id": provider_id,
        "entry_point": "provider.py:PluginProvider",
        "manifest": {
            "display_name": "Sample TTS",
            "locality": "cloud",
            "credential_mode": "profile_or_key",
            "setup_kind": "credential",
            "placeholder_api_key": True,
            "profile_management_ready": True,
            "controls": {
                "api_profile": True,
                "api_key": True,
                "voice_browser_fallback": True,
                "model_listing_fallback": True,
            },
        },
    }
    (root / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    source = code or f'''from app.plugin_sdk import AppSettings, ProviderCapabilities, TTSProvider

class PluginProvider(TTSProvider):
    provider_id={provider_id!r}
    display_name="Sample TTS"
    def __init__(self, settings: AppSettings): self.settings=settings
    def capabilities(self):
        return ProviderCapabilities(
            self.provider_id,
            self.display_name,
            remote=True,
            requires_credential=True,
            supports_voice_listing=True,
            supports_model_listing=True,
        )
    def synthesize(self,text,settings): return b"RIFFplugin"
    def list_voices(self): return [{{"voice_id":"sample","name":"Sample"}}]
    def list_models(self): return [{{"model_id":"sample-v1","name":"Sample v1"}}]
'''
    (root / "provider.py").write_text(source, encoding="utf-8")
    return root


def _service(
    tmp_path: Path,
    registry: ProviderRegistry | None = None,
) -> ProviderPluginSDKService:
    return ProviderPluginSDKService(
        tmp_path / "plugins",
        tmp_path / "evidence",
        registry=registry or _base_registry(),
    )


def test_phase111_sdk_version_is_stable() -> None:
    assert PLUGIN_SDK_API_VERSION == 1


def test_phase111_discovery_does_not_execute_plugin_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    plugin = _plugin(
        tmp_path / "plugins" / "sample",
        code=f'''from pathlib import Path
Path({str(marker)!r}).write_text("executed")
from app.plugin_sdk import TTSProvider
class PluginProvider(TTSProvider):
    provider_id="sample_tts"
    display_name="Sample"
    def synthesize(self,text,settings): return b""
    def list_voices(self): return []
    def list_models(self): return []
''',
    )
    candidates = _service(tmp_path).discover(plugin.parent)
    assert candidates[0].state == "compatible"
    assert not marker.exists()


def test_phase111_discovery_fingerprint_changes_with_code(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path)
    first = service.discover(plugin)[0].descriptor
    assert first is not None
    (plugin / "provider.py").write_text(
        (plugin / "provider.py").read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )
    second = service.discover(plugin)[0].descriptor
    assert second is not None
    assert first.fingerprint != second.fingerprint


def test_phase111_activation_requires_explicit_approval(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path)
    candidate = service.discover(plugin)[0]
    with pytest.raises(Exception, match="explicit user approval"):
        service.activate(candidate, approved=False)


def test_phase111_activation_is_blocked_during_generation(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path)
    candidate = service.discover(plugin)[0]
    with pytest.raises(Exception, match="Stop active generation"):
        service.activate(candidate, approved=True, generation_active=True)


def test_phase111_activation_rejects_post_scan_drift(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path)
    candidate = service.discover(plugin)[0]
    (plugin / "provider.py").write_text(
        (plugin / "provider.py").read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="changed after discovery"):
        service.activate(candidate, approved=True)


def test_phase111_activation_registers_factory_and_manifest_for_session(
    tmp_path: Path,
) -> None:
    registry = _base_registry()
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path, registry)
    candidate = service.discover(plugin)[0]
    try:
        activation = service.activate(candidate, approved=True)
        assert activation.provider_id == "sample_tts"
        assert "sample_tts" in available_provider_ids()
        assert registry.manifest_for("sample_tts").display_name == "Sample TTS"
        provider = create_provider(AppSettings(provider="sample_tts", api_key="x"))
        assert provider.provider_id == "sample_tts"
        assert provider.list_models()[0]["model_id"] == "sample-v1"
    finally:
        if "sample_tts" in registry.plugin_provider_ids():
            service.deactivate(
                "sample_tts",
                approved=True,
                active_provider_id="mock",
            )


def test_phase111_dynamic_identity_uses_plugin_manifest_display_name(
    tmp_path: Path,
) -> None:
    registry = _base_registry()
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path, registry)
    candidate = service.discover(plugin)[0]
    try:
        service.activate(candidate, approved=True)
        identity = ProviderIdentityService(registry=registry).identity_for("sample_tts")
        assert identity.display_name == "Sample TTS"
        assert identity.locality == "Cloud"
    finally:
        service.deactivate("sample_tts", approved=True, active_provider_id="mock")


def test_phase111_activation_receipt_contains_hashes_not_credentials(
    tmp_path: Path,
) -> None:
    registry = _base_registry()
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path, registry)
    candidate = service.discover(plugin)[0]
    try:
        activation = service.activate(candidate, approved=True)
        payload = json.loads(activation.receipt_path.read_text(encoding="utf-8"))
        assert payload["fingerprint"] == activation.fingerprint
        assert payload["manifest_sha256"]
        assert payload["code_sha256"]
        assert payload["activation_scope"] == "session"
        assert payload["automatic_startup_loading"] is False
        assert "credential_value" not in payload
        assert "api_key_value" not in payload
        assert "source_path" not in payload
    finally:
        service.deactivate("sample_tts", approved=True, active_provider_id="mock")


def test_phase111_builtin_provider_id_collision_is_blocked(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path / "plugins" / "sample",
        provider_id="openai",
    )
    service = _service(tmp_path)
    candidate = service.discover(plugin)[0]
    assert candidate.state == "blocked"
    with pytest.raises(Exception):
        service.activate(candidate, approved=True)


def test_phase111_entrypoint_must_stay_inside_plugin_directory(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    payload = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    payload["entry_point"] = "../outside.py:PluginProvider"
    (plugin / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    (plugin.parent / "outside.py").write_text(
        "class PluginProvider: pass",
        encoding="utf-8",
    )
    candidate = _service(tmp_path).discover(plugin)[0]
    assert candidate.state == "invalid"
    assert "inside" in candidate.message


def test_phase111_unknown_manifest_fields_are_rejected(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    payload = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    payload["manifest"]["magic_failover"] = True
    (plugin / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    candidate = _service(tmp_path).discover(plugin)[0]
    assert candidate.state == "invalid"
    assert "Unknown provider manifest fields" in candidate.message


def test_phase111_wrong_sdk_version_is_rejected(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins" / "sample")
    payload = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    payload["sdk_api_version"] = 999
    (plugin / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    candidate = _service(tmp_path).discover(plugin)[0]
    assert candidate.state == "invalid"
    assert "Unsupported plugin SDK API version" in candidate.message


def test_phase111_provider_class_must_match_manifest_provider_id(
    tmp_path: Path,
) -> None:
    plugin = _plugin(
        tmp_path / "plugins" / "sample",
        code='''from app.plugin_sdk import TTSProvider
class PluginProvider(TTSProvider):
    provider_id="wrong_id"
    display_name="Wrong"
    def synthesize(self,text,settings): return b""
    def list_voices(self): return []
    def list_models(self): return []
''',
    )
    service = _service(tmp_path)
    candidate = service.discover(plugin)[0]
    with pytest.raises(Exception, match="does not match"):
        service.activate(candidate, approved=True)


def test_phase111_deactivation_requires_explicit_approval(tmp_path: Path) -> None:
    registry = _base_registry()
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path, registry)
    candidate = service.discover(plugin)[0]
    service.activate(candidate, approved=True)
    try:
        with pytest.raises(Exception, match="explicit user approval"):
            service.deactivate(
                "sample_tts",
                approved=False,
                active_provider_id="mock",
            )
    finally:
        service.deactivate("sample_tts", approved=True, active_provider_id="mock")


def test_phase111_deactivation_cannot_remove_selected_provider(
    tmp_path: Path,
) -> None:
    registry = _base_registry()
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path, registry)
    candidate = service.discover(plugin)[0]
    service.activate(candidate, approved=True)
    try:
        with pytest.raises(Exception, match="Select a different provider"):
            service.deactivate(
                "sample_tts",
                approved=True,
                active_provider_id="sample_tts",
            )
    finally:
        service.deactivate("sample_tts", approved=True, active_provider_id="mock")


def test_phase111_deactivation_cannot_run_during_generation(
    tmp_path: Path,
) -> None:
    registry = _base_registry()
    plugin = _plugin(tmp_path / "plugins" / "sample")
    service = _service(tmp_path, registry)
    candidate = service.discover(plugin)[0]
    service.activate(candidate, approved=True)
    try:
        with pytest.raises(Exception, match="Stop active generation"):
            service.deactivate(
                "sample_tts",
                approved=True,
                active_provider_id="mock",
                generation_active=True,
            )
    finally:
        service.deactivate("sample_tts", approved=True, active_provider_id="mock")


def test_phase111_scaffold_creates_discoverable_sdk_v1_template(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    target = service.scaffold(
        tmp_path / "starter",
        provider_id="starter_tts",
        display_name="Starter TTS",
    )
    assert (target / "plugin.json").exists()
    assert (target / "provider.py").exists()
    assert (target / "README.md").exists()
    candidate = service.discover(target)[0]
    assert candidate.state == "compatible"
    assert candidate.provider_id == "starter_tts"


def test_phase111_no_automatic_provider_switch_or_generation_start_contract() -> None:
    service_source = Path(
        "app/services/provider_plugin_sdk_service.py"
    ).read_text(encoding="utf-8")
    main_source = Path("app/gui/main.py").read_text(encoding="utf-8")
    docs = Path("docs/PROVIDER_PLUGIN_SDK_PHASE111.md").read_text(
        encoding="utf-8"
    )
    assert "activate(" in service_source
    assert "approved" in service_source
    assert "generation_active" in service_source
    assert "provider.setCurrentText(provider_id)" not in main_source
    assert "self.start()" not in service_source
    assert "cross-provider" in docs
    assert "does not auto-load" in docs


def test_phase111_does_not_change_database_schema() -> None:
    from app.release import SCHEMA_VERSION

    assert SCHEMA_VERSION == 23
