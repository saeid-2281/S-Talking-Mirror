from __future__ import annotations

import json
import threading
import wave
from pathlib import Path

import pytest

from app.config.runtime import RuntimeConfig
from app.database.connection import Database
from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.kokoro_runtime import (
    KOKORO_VOICES,
    KokoroRuntimeService,
)
from app.providers.optional_adapters import KokoroLocalProvider
from app.services.offline_tts_engine_service import OfflineTTSEngineService
from app.services.piper_model_manager import PiperModelManager
from app.services.queue_service import QueueService
from app.services.voice_service import VoiceService

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "app" / "gui" / "worker.py"
PREFLIGHT = ROOT / "app" / "services" / "preflight_service.py"
REPORT = ROOT / "app" / "services" / "report_service.py"
VERIFICATION = ROOT / "app" / "services" / "provider_verification_service.py"
DIALOG = ROOT / "app" / "gui" / "dialogs" / "offline_tts_engines_dialog.py"
PYPROJECT = ROOT / "pyproject.toml"


def _piper_voice(root: Path, name: str = "da_DK-test-medium") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    model = root / f"{name}.onnx"
    model.write_bytes(b"piper-model-v1")
    Path(f"{model}.json").write_text(
        json.dumps(
            {
                "dataset": name,
                "language": {"code": "da_DK"},
                "audio": {"sample_rate": 22050},
                "num_speakers": 1,
            }
        ),
        encoding="utf-8",
    )
    return model


class _FakePipeline:
    init_codes: list[str] = []
    calls: list[tuple[str, str, float]] = []

    def __init__(self, *, lang_code: str) -> None:
        self.lang_code = lang_code
        self.init_codes.append(lang_code)

    def __call__(self, text: str, *, voice: str, speed: float):
        self.calls.append((text, voice, speed))
        yield text, "phonemes", [0.0, 0.25, -0.25, 0.5]


class _FakeKokoroModule:
    KPipeline = _FakePipeline


def _kokoro_runtime() -> KokoroRuntimeService:
    _FakePipeline.init_codes = []
    _FakePipeline.calls = []
    return KokoroRuntimeService(kokoro_loader=lambda: _FakeKokoroModule())


def test_phase102_piper_model_manager_is_explicit_and_inventory_stays_read_only(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    manager = PiperModelManager(runtime)
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda _name: None,
        executable_finder=lambda _name: None,
        piper_model_manager=manager,
    )

    assert manager.managed_root.exists() is False
    service.inventory(AppSettings(provider="mock"))
    assert manager.managed_root.exists() is False


def test_phase102_piper_model_manager_imports_model_config_and_model_card(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    source = tmp_path / "incoming"
    model = _piper_voice(source)
    (source / "MODEL_CARD").write_text("license metadata", encoding="utf-8")
    manager = PiperModelManager(runtime)

    managed = manager.import_voice(model)

    assert managed.managed is True
    assert managed.model_path.is_file()
    assert managed.config_path.is_file()
    assert managed.language_code == "da_DK"
    assert managed.sample_rate == 22050
    assert managed.speaker_count == 1
    assert (managed.model_path.parent / "MODEL_CARD").read_text(encoding="utf-8") == "license metadata"


def test_phase102_piper_import_is_idempotent_for_identical_bytes_and_rejects_conflict(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    model = _piper_voice(tmp_path / "incoming")
    manager = PiperModelManager(runtime)
    first = manager.import_voice(model)
    second = manager.import_voice(model)
    assert second.model_path == first.model_path

    model.write_bytes(b"different-model")
    with pytest.raises(FileExistsError):
        manager.import_voice(model)


def test_phase102_piper_import_requires_adjacent_config(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    with pytest.raises(ConfigurationError, match="config"):
        PiperModelManager(runtime).import_voice(model)


def test_phase102_piper_import_rejects_empty_model_and_invalid_config(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    manager = PiperModelManager(runtime)

    empty_model = tmp_path / "empty.onnx"
    empty_model.write_bytes(b"")
    Path(f"{empty_model}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="empty"):
        manager.import_voice(empty_model)

    invalid_model = tmp_path / "invalid.onnx"
    invalid_model.write_bytes(b"model")
    Path(f"{invalid_model}.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid"):
        manager.import_voice(invalid_model)


def test_phase102_offline_inventory_discovers_recursively_imported_piper_voice(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    model = _piper_voice(tmp_path / "incoming")
    manager = PiperModelManager(runtime)
    managed = manager.import_voice(model)
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda name: object() if name == "piper" else None,
        executable_finder=lambda _name: None,
        piper_model_manager=manager,
    )

    voices = service.discover_voices("piper", AppSettings(provider="piper", piper_model_path=str(managed.model_path)))
    assert len(voices) == 1
    assert voices[0].voice_id == managed.voice_id
    assert voices[0].config_present is True
    assert voices[0].selected is True


def test_phase102_kokoro_catalog_matches_official_v1_language_voice_contract() -> None:
    runtime = _kokoro_runtime()
    assert len(KOKORO_VOICES) == 54
    assert {spec.pipeline_code for spec in runtime.supported_languages()} == {"a", "b", "e", "f", "h", "i", "j", "p", "z"}
    assert runtime.language_spec("en-US").pipeline_code == "a"
    assert runtime.language_spec("en_GB").pipeline_code == "b"
    assert runtime.language_spec("da-DK") is None
    assert runtime.language_spec("da") is None
    assert {voice.voice_id for voice in runtime.voices_for_language("fr-FR")} == {"ff_siwis"}


def test_phase102_kokoro_danish_is_explicitly_not_certified() -> None:
    runtime = _kokoro_runtime()
    issue = runtime.certification_issue("da-DK")
    assert issue is not None
    assert "not certified" in issue
    assert "does not include Danish" in issue


def test_phase102_kokoro_provider_blocks_danish_even_when_runtime_dependency_is_present(monkeypatch) -> None:
    runtime = _kokoro_runtime()
    provider = KokoroLocalProvider(
        AppSettings(provider="kokoro", language_code="da-DK", voice_id="af_heart"),
        runtime=runtime,
    )
    monkeypatch.setattr(provider, "dependency_available", lambda: True)
    result = provider.validate_configuration(provider.settings)
    assert result.ok is False
    assert "does not include Danish" in result.message


def test_phase102_kokoro_provider_requires_compatible_explicit_voice(monkeypatch) -> None:
    runtime = _kokoro_runtime()
    missing = KokoroLocalProvider(
        AppSettings(provider="kokoro", language_code="en-US", voice_id=""),
        runtime=runtime,
    )
    monkeypatch.setattr(missing, "dependency_available", lambda: True)
    assert missing.validate_configuration(missing.settings).ok is False

    wrong = KokoroLocalProvider(
        AppSettings(provider="kokoro", language_code="fr-FR", voice_id="af_heart"),
        runtime=runtime,
    )
    monkeypatch.setattr(wrong, "dependency_available", lambda: True)
    result = wrong.validate_configuration(wrong.settings)
    assert result.ok is False
    assert "not fr-FR" in result.message


def test_phase102_kokoro_provider_lists_only_certified_language_voices(monkeypatch) -> None:
    provider = KokoroLocalProvider(
        AppSettings(provider="kokoro", language_code="fr-FR", voice_id="ff_siwis"),
        runtime=_kokoro_runtime(),
    )
    monkeypatch.setattr(provider, "dependency_available", lambda: True)
    voices = provider.list_voices()
    assert [voice["voice_id"] for voice in voices] == ["ff_siwis"]
    assert provider.list_models()[0]["model_id"] == "kokoro-82m-v1.0"


def test_phase102_kokoro_runtime_reuses_pipeline_and_outputs_valid_wav(tmp_path: Path) -> None:
    runtime = _kokoro_runtime()
    first = runtime.synthesize(
        "Hello",
        language_code="en-US",
        voice_id="af_heart",
        speed=1.1,
    )
    second = runtime.synthesize(
        "Again",
        language_code="en-US",
        voice_id="af_bella",
        speed=0.9,
    )

    assert first.startswith(b"RIFF")
    assert second.startswith(b"RIFF")
    assert _FakePipeline.init_codes == ["a"]
    assert _FakePipeline.calls == [("Hello", "af_heart", 1.1), ("Again", "af_bella", 0.9)]
    health = runtime.health()
    assert health.pipeline_count == 1
    assert health.load_count == 1
    assert health.synthesis_count == 2

    output = tmp_path / "phase102-kokoro.wav"
    output.write_bytes(first)
    try:
        with wave.open(str(output), "rb") as wav_file:
            assert wav_file.getframerate() == 24000
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getnframes() > 0
    finally:
        output.unlink(missing_ok=True)


def test_phase102_kokoro_runtime_uses_existing_cancellation_contract() -> None:
    runtime = _kokoro_runtime()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ProviderError) as exc_info:
        runtime.synthesize(
            "Stop",
            language_code="en-US",
            voice_id="af_heart",
            cancel_event=cancelled,
        )
    assert exc_info.value.provider_code == "cancelled"


def test_phase102_offline_snapshot_keeps_kokoro_installed_but_not_ready_for_danish(tmp_path: Path) -> None:
    service = OfflineTTSEngineService(
        RuntimeConfig.from_root(tmp_path),
        module_finder=lambda name: object() if name == "kokoro" else None,
        executable_finder=lambda _name: None,
        kokoro_runtime=_kokoro_runtime(),
    )
    snapshot = service.snapshot(
        "kokoro",
        AppSettings(provider="kokoro", language_code="da-DK", voice_id=""),
    )
    assert snapshot.installed is True
    assert snapshot.ready is False
    assert snapshot.state == "Language not certified"
    assert any("does not include Danish" in issue for issue in snapshot.issues)


def test_phase102_offline_snapshot_can_warm_and_restart_certified_kokoro(tmp_path: Path) -> None:
    runtime = _kokoro_runtime()
    service = OfflineTTSEngineService(
        RuntimeConfig.from_root(tmp_path),
        module_finder=lambda name: object() if name == "kokoro" else None,
        executable_finder=lambda _name: None,
        kokoro_runtime=runtime,
    )
    settings = AppSettings(provider="kokoro", language_code="en-US", voice_id="af_heart")
    cold = service.snapshot("kokoro", settings)
    assert cold.ready is True
    assert cold.runtime_loaded is False
    service.warm_kokoro(settings)
    warm = service.snapshot("kokoro", settings)
    assert warm.runtime_loaded is True
    assert warm.runtime_cache_entries == 1
    assert service.restart_kokoro(settings) == 1
    assert service.snapshot("kokoro", settings).runtime_loaded is False


def test_phase102_manifest_centralizes_forced_local_wav_policy() -> None:
    assert DEFAULT_PROVIDER_REGISTRY.output_extension("mock", ".mp3") == ".wav"
    assert DEFAULT_PROVIDER_REGISTRY.output_extension("piper", ".mp3") == ".wav"
    assert DEFAULT_PROVIDER_REGISTRY.output_extension("kokoro", ".mp3") == ".wav"
    assert DEFAULT_PROVIDER_REGISTRY.output_extension("elevenlabs", ".mp3") == ".mp3"
    assert QueueService.extension_for(AppSettings(provider="kokoro", file_extension=".mp3")) == ".wav"
    assert VoiceService._preview_extension(AppSettings(provider="kokoro", file_extension=".mp3")) == ".wav"


def test_phase102_output_paths_consume_manifest_policy_instead_of_local_provider_sets() -> None:
    for path in (WORKER, PREFLIGHT, REPORT, VERIFICATION):
        source = path.read_text(encoding="utf-8")
        assert "DEFAULT_PROVIDER_REGISTRY.output_extension" in source
        assert '{"mock", "piper"}' not in source
        assert "{'mock', 'piper'}" not in source


def test_phase102_offline_dialog_exposes_explicit_piper_import_and_kokoro_lifecycle() -> None:
    source = DIALOG.read_text(encoding="utf-8")
    assert "Import Piper voice…" in source
    assert "def import_piper_voice" in source
    assert "def warm_kokoro_runtime" in source
    assert "def restart_kokoro_runtime" in source
    assert "getOpenFileName" in source
    assert "download" not in source[source.index("    def import_piper_voice"):].casefold()


def test_phase102_optional_dependency_targets_official_kokoro_api_line() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'kokoro=["kokoro>=0.9.4,<1"]' in text
    assert '"kokoro>=0.9.4,<1"' in text


def test_phase102_does_not_change_database_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase102-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23


def test_phase102_does_not_register_xtts_or_add_hidden_provider_switching() -> None:
    provider_ids = DEFAULT_PROVIDER_REGISTRY.provider_ids()
    assert "xtts" not in provider_ids
    runtime_source = (ROOT / "app" / "providers" / "kokoro_runtime.py").read_text(encoding="utf-8")
    adapter_source = (ROOT / "app" / "providers" / "optional_adapters.py").read_text(encoding="utf-8")
    assert "create_provider(" not in runtime_source
    assert "create_provider(" not in adapter_source[adapter_source.index("class KokoroLocalProvider"):]
