from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models import AppSettings
from app.providers.piper import PiperProvider
from app.providers.piper_installation import resolve_piper_model_path
from app.services.offline_tts_engine_service import OfflineTTSEngineService


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"
MAIN = ROOT / "app" / "gui" / "main.py"
PREFLIGHT = ROOT / "app" / "services" / "preflight_service.py"
FROZEN = ROOT / "app" / "frozen_main.py"


class _NoPythonRuntime:
    @staticmethod
    def api_available() -> bool:
        return False


def _runtime(tmp_path: Path) -> tuple[RuntimeConfig, Path]:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    model = (
        runtime.data_dir
        / "offline-voices"
        / "piper"
        / "da_DK-talesyntese-medium"
        / "da_DK-talesyntese-medium.onnx"
    )
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"onnx")
    Path(f"{model}.json").write_text("{}", encoding="utf-8")
    return runtime, model


def test_h4_rebases_only_missing_managed_portable_piper_path(tmp_path: Path) -> None:
    runtime, model = _runtime(tmp_path)
    stale = (
        r"C:\ST Wpro\S-Talking-B7-old-Portable-Windows-x64"
        r"\S-Talking-Data\data\offline-voices\piper"
        r"\da_DK-talesyntese-medium\da_DK-talesyntese-medium.onnx"
    )

    resolved = resolve_piper_model_path(stale, runtime)

    assert resolved is not None
    assert resolved.resolve() == model.resolve()

    external = tmp_path.parent / "external-missing.onnx"
    assert resolve_piper_model_path(external, runtime) == external


def test_h4_offline_inventory_treats_rebased_managed_voice_as_selected(tmp_path: Path) -> None:
    runtime, model = _runtime(tmp_path)
    stale = (
        r"C:\ST Wpro\S-Talking-B7-old-Portable-Windows-x64"
        r"\S-Talking-Data\offline-voices\piper"
        r"\da_DK-talesyntese-medium\da_DK-talesyntese-medium.onnx"
    )
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda _name: None,
        executable_finder=lambda _name: None,
    )

    voices = service.discover_voices(
        "piper",
        AppSettings(provider="piper", piper_model_path=stale),
    )

    assert len(voices) == 1
    assert voices[0].selected is True
    assert Path(voices[0].model_path).resolve() == model.resolve()


def test_h4_provider_accepts_rebased_model_identity_when_cli_is_managed(tmp_path: Path) -> None:
    runtime, model = _runtime(tmp_path)
    engine = runtime.data_dir.parent / "local-engines" / "piper"
    wrapper = engine / ".venv" / "Scripts" / "piper.exe"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_bytes(b"stub")

    stale = (
        r"C:\ST Wpro\S-Talking-B7-old-Portable-Windows-x64"
        r"\S-Talking-Data\data\offline-voices\piper"
        r"\da_DK-talesyntese-medium\da_DK-talesyntese-medium.onnx"
    )
    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=stale),
        runtime=_NoPythonRuntime(),
        runtime_config=runtime,
        executable_finder=lambda _name: None,
    )

    assert provider.model.resolve() == model.resolve()
    assert provider.validate_configuration(
        AppSettings(provider="piper", piper_model_path=stale)
    ).ok is True


def test_h4_migration_separates_engine_and_state_sources_and_uses_canonical_voice_root() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "StateSourcePortableRoot" in source
    assert "StateSourceData" in source
    assert 'DestinationRuntimeData = Join-Path $DestinationData "data"' in source
    assert 'CanonicalVoiceDestination = Join-Path $DestinationRuntimeData "offline-voices"' in source
    assert "legacy -> canonical" in source
    assert "LOCAL_ENGINES_PIPER_SYNTHESIS_SMOKE=PASS" in source


def test_h4_ui_and_preflight_share_managed_path_rebase() -> None:
    main = MAIN.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")

    assert "resolve_piper_model_path" in main
    assert "resolved_piper_model_text" in main
    assert "resolve_piper_model_path" in preflight
    assert "resolved_piper_model = resolve_piper_model_path(" in preflight


def test_h4_frozen_verifier_preserves_read_only_boundary_and_separate_real_synthesis() -> None:
    source = FROZEN.read_text(encoding="utf-8")
    smoke_handler = source.split(
        "def _handle_local_engines_piper_synthesis_smoke", 1
    )[1].split("def _handle_local_engines_runtime_verify", 1)[0]
    verify_handler = source.split("def _handle_local_engines_runtime_verify", 1)[1].split(
        "def _handle_provider_accounts_runtime_verify", 1
    )[0]

    assert "--local-engines-stale-model-path" in verify_handler
    assert "LOCAL_ENGINES_STALE_MODEL_REBASE" in verify_handler
    assert ".synthesize(" not in verify_handler
    assert "--local-engines-piper-synthesis-smoke" in smoke_handler
    assert "LOCAL_ENGINES_PIPER_SYNTHESIS_SMOKE" in smoke_handler
    assert 'smoke_provider.synthesize("Hej.", smoke_settings)' in smoke_handler
