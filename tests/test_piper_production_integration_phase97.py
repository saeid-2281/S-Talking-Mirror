from __future__ import annotations

import json
import types
import wave
from pathlib import Path

import pytest

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.exceptions import ProviderError
from app.gui.dialogs.offline_tts_engines_dialog import OfflineTTSEnginesDialog
from app.models import AppSettings
from app.providers.piper import PiperProvider
from app.services.offline_tts_engine_service import OfflineTTSEngineService
from app.providers.piper_runtime import PiperRuntimeService


ROOT = Path(__file__).resolve().parents[1]
PIPER_PROVIDER = ROOT / "app" / "providers" / "piper.py"
PIPER_RUNTIME = ROOT / "app" / "providers" / "piper_runtime.py"
PYPROJECT = ROOT / "pyproject.toml"
DIALOG = ROOT / "app" / "gui" / "dialogs" / "offline_tts_engines_dialog.py"


class _Chunk:
    sample_rate = 22050
    sample_width = 2
    sample_channels = 1
    audio_int16_bytes = b"\x00\x00" * 64


class _FakeVoice:
    def __init__(self) -> None:
        self.synthesis_configs: list[object] = []

    def synthesize(self, _text: str, **kwargs):
        self.synthesis_configs.append(kwargs.get("syn_config"))
        yield _Chunk()
        yield _Chunk()


class _FakePiperVoice:
    load_calls: list[tuple[str, bool]] = []
    fail_cuda = False
    voices: list[_FakeVoice] = []

    @classmethod
    def reset(cls) -> None:
        cls.load_calls = []
        cls.fail_cuda = False
        cls.voices = []

    @classmethod
    def load(cls, model_path: str, *, use_cuda: bool = False):
        cls.load_calls.append((model_path, use_cuda))
        if use_cuda and cls.fail_cuda:
            raise RuntimeError("CUDA provider failed")
        voice = _FakeVoice()
        cls.voices.append(voice)
        return voice


class _FakeSynthesisConfig:
    def __init__(self, *, length_scale: float = 1.0) -> None:
        self.length_scale = length_scale


def _piper_module():
    return types.SimpleNamespace(
        PiperVoice=_FakePiperVoice,
        SynthesisConfig=_FakeSynthesisConfig,
    )


def _voice(tmp_path: Path) -> Path:
    model = tmp_path / "voices" / "da_DK-talesyntese-medium.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"onnx")
    Path(f"{model}.json").write_text(
        json.dumps(
            {
                "dataset": "talesyntese",
                "language": {"code": "da_DK"},
                "audio": {"sample_rate": 22050},
                "num_speakers": 1,
            }
        ),
        encoding="utf-8",
    )
    return model


def _runtime(*, cuda: bool = False) -> PiperRuntimeService:
    providers = ("CUDAExecutionProvider", "CPUExecutionProvider") if cuda else ("CPUExecutionProvider",)
    return PiperRuntimeService(
        piper_loader=_piper_module,
        execution_provider_loader=lambda: providers,
    )


def test_phase97_runtime_reuses_loaded_model_across_syntheses(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime = _runtime()

    first = runtime.synthesize("Hej", model)
    second = runtime.synthesize("Igen", model)
    health = runtime.health(model)

    assert first.startswith(b"RIFF")
    assert second.startswith(b"RIFF")
    assert _FakePiperVoice.load_calls == [(str(model), False)]
    assert health.loaded is True
    assert health.resolved_acceleration == "cpu"
    assert health.load_count == 1
    assert health.synthesis_count == 2


def test_phase97_runtime_outputs_valid_wav_and_maps_speed_to_length_scale(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime = _runtime()

    audio = runtime.synthesize("Dansk lyd", model, speed=1.2)

    output = tmp_path / "sample.wav"
    output.write_bytes(audio)
    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getframerate() == 22050
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() > 0
    config = _FakePiperVoice.voices[0].synthesis_configs[0]
    assert config.length_scale == pytest.approx(1 / 1.2)


def test_phase97_auto_prefers_cuda_when_onnx_cuda_provider_is_available(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime = _runtime(cuda=True)

    runtime.warm(model)
    health = runtime.health(model)

    assert _FakePiperVoice.load_calls == [(str(model), True)]
    assert health.resolved_acceleration == "cuda"
    assert health.cuda_available is True


def test_phase97_auto_falls_back_to_cpu_once_when_cuda_model_load_fails(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    _FakePiperVoice.fail_cuda = True
    model = _voice(tmp_path)
    runtime = _runtime(cuda=True)

    runtime.synthesize("Første", model)
    runtime.synthesize("Anden", model)
    health = runtime.health(model)

    assert _FakePiperVoice.load_calls == [(str(model), True), (str(model), False)]
    assert health.resolved_acceleration == "cpu"
    assert health.fallback_reason is not None
    assert "fell back to CPU" in health.fallback_reason


def test_phase97_runtime_cancellation_uses_existing_provider_cancel_contract(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime = _runtime()
    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=str(model)),
        runtime=runtime,
        executable_finder=lambda _name: None,
    )

    provider.cancel()
    with pytest.raises(ProviderError) as exc_info:
        runtime.synthesize("Stop", model, cancel_event=provider._cancel_event)
    assert exc_info.value.provider_code == "cancelled"


def test_phase97_provider_prefers_python_runtime_and_keeps_legacy_cli_as_fallback(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=str(model)),
        runtime=_runtime(),
        executable_finder=lambda _name: "C:/legacy/piper.exe",
    )
    assert provider.runtime_mode == "python-api"
    assert provider.synthesize("Hej", provider.settings).startswith(b"RIFF")
    source = PIPER_PROVIDER.read_text(encoding="utf-8")
    assert "subprocess.Popen" in source
    assert "self.runtime.synthesize" in source
    assert "except PiperRuntimeUnavailable" in source


def test_phase97_provider_capabilities_expose_speed_streaming_and_cancellation(tmp_path: Path) -> None:
    model = _voice(tmp_path)
    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=str(model)),
        runtime=_runtime(),
        executable_finder=lambda _name: None,
    )
    capabilities = provider.capabilities()
    assert capabilities.supports_speed is True
    assert capabilities.supports_streaming is True
    assert capabilities.supports_cancellation is True
    assert capabilities.supported_output_formats == ("wav",)


def test_phase97_offline_inventory_reflects_warm_runtime_and_auto_accelerator(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime_config = RuntimeConfig.from_root(tmp_path)
    runtime_config.ensure_directories()
    piper_runtime = _runtime(cuda=True)
    service = OfflineTTSEngineService(
        runtime_config,
        module_finder=lambda name: object() if name == "piper" else None,
        executable_finder=lambda _name: None,
        piper_runtime=piper_runtime,
    )
    settings = AppSettings(provider="piper", piper_model_path=str(model))

    cold = service.snapshot("piper", settings)
    service.warm_piper(settings)
    warm = service.snapshot("piper", settings)

    assert cold.runtime_loaded is False
    assert warm.runtime_loaded is True
    assert warm.resolved_accelerator == "cuda"
    assert warm.state == "Runtime warm"
    assert warm.runtime_load_count == 1


def test_phase97_runtime_restart_clears_selected_model_cache(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime = _runtime()
    runtime.warm(model)
    assert runtime.health(model).loaded is True
    assert runtime.restart(model) == 1
    assert runtime.health(model).loaded is False


def test_phase97_restart_resets_auto_cuda_fallback_for_next_warmup(tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    _FakePiperVoice.fail_cuda = True
    model = _voice(tmp_path)
    runtime = _runtime(cuda=True)
    runtime.warm(model)
    assert runtime.health(model).resolved_acceleration == "cpu"

    runtime.restart(model)
    _FakePiperVoice.fail_cuda = False
    runtime.warm(model)

    assert _FakePiperVoice.load_calls == [
        (str(model), True),
        (str(model), False),
        (str(model), True),
    ]
    assert runtime.health(model).resolved_acceleration == "cuda"


def test_phase97_runtime_is_shared_through_container_and_application_context(tmp_path: Path) -> None:
    runtime_config = RuntimeConfig.from_root(tmp_path)
    runtime_config.ensure_directories()
    container = create_service_container(runtime_config)
    context = create_application_context(container)
    assert context.piper_runtime_service is container.piper_runtime_service
    assert container.offline_tts_engine_service.piper_runtime is container.piper_runtime_service


def test_phase97_dialog_exposes_warm_restart_without_starting_generation(qt_app, tmp_path: Path) -> None:
    _FakePiperVoice.reset()
    model = _voice(tmp_path)
    runtime_config = RuntimeConfig.from_root(tmp_path)
    runtime_config.ensure_directories()
    service = OfflineTTSEngineService(
        runtime_config,
        module_finder=lambda name: object() if name == "piper" else None,
        executable_finder=lambda _name: None,
        piper_runtime=_runtime(),
    )
    settings = AppSettings(provider="piper", piper_model_path=str(model))
    dialog = OfflineTTSEnginesDialog(service, lambda: settings, generation_active=lambda: False)
    dialog.show()
    qt_app.processEvents()

    assert dialog.warm_runtime_button.isEnabled() is True
    dialog.warm_piper_runtime()
    assert service.piper_runtime_health(settings).loaded is True
    dialog.restart_piper_runtime()
    assert service.piper_runtime_health(settings).loaded is False

    source = DIALOG.read_text(encoding="utf-8")
    warm_segment = source[source.index("    def warm_piper_runtime"):source.index("    def selected_voice")]
    assert ".start(" not in warm_segment
    assert "retry" not in warm_segment.casefold()


def test_phase97_dialog_blocks_runtime_lifecycle_changes_during_generation(qt_app, tmp_path: Path) -> None:
    model = _voice(tmp_path)
    runtime_config = RuntimeConfig.from_root(tmp_path)
    runtime_config.ensure_directories()
    service = OfflineTTSEngineService(
        runtime_config,
        module_finder=lambda name: object() if name == "piper" else None,
        executable_finder=lambda _name: None,
        piper_runtime=_runtime(),
    )
    dialog = OfflineTTSEnginesDialog(
        service,
        lambda: AppSettings(provider="piper", piper_model_path=str(model)),
        generation_active=lambda: True,
    )
    dialog.show()
    qt_app.processEvents()
    assert dialog.warm_runtime_button.isEnabled() is False
    assert dialog.restart_runtime_button.isEnabled() is False


def test_phase97_runtime_service_serializes_each_cached_model() -> None:
    source = PIPER_RUNTIME.read_text(encoding="utf-8")
    assert "with slot.lock:" in source
    assert "OrderedDict" in source
    assert "max_cache_entries" in source


def test_phase97_optional_dependency_targets_current_stable_piper_line() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'piper=["piper-tts>=1.4.2,<2"]' in text
    assert '"piper-tts>=1.4.2,<2"' in text


def test_phase97_does_not_add_database_migrations() -> None:
    runtime_source = PIPER_RUNTIME.read_text(encoding="utf-8")
    provider_source = PIPER_PROVIDER.read_text(encoding="utf-8")
    assert "schema_migrations" not in runtime_source
    assert "schema_migrations" not in provider_source
    assert "INSERT " not in runtime_source.upper()
    assert "UPDATE " not in runtime_source.upper()
    assert "DELETE " not in runtime_source.upper()


def test_phase97_provider_readiness_accepts_legacy_cli_when_python_module_is_missing(monkeypatch) -> None:
    import app.services.provider_readiness_service as readiness_module

    monkeypatch.setattr(readiness_module.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(readiness_module.shutil, "which", lambda name: "C:/piper.exe" if name == "piper" else None)
    assert readiness_module.ProviderReadinessService._dependency_installed("piper") is True


def test_phase97_release_readiness_accepts_python_api_without_cli(monkeypatch, tmp_path: Path) -> None:
    import app.services.release_readiness_service as release_module

    model = _voice(tmp_path)
    monkeypatch.setattr(release_module.importlib.util, "find_spec", lambda name: object() if name == "piper" else None)
    monkeypatch.setattr(release_module.shutil, "which", lambda _name: None)
    state = release_module.ReleaseReadinessService.provider_status(
        object(),
        AppSettings(provider="piper", piper_model_path=str(model)),
    )
    assert state.connection_state == "ready"
    assert state.model_availability == "available"
    assert state.voice_accessibility == "local"
