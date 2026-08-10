from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.gui.dialogs.offline_tts_engines_dialog import OfflineTTSEnginesDialog
from app.models import AppSettings
from app.services.offline_tts_engine_service import OfflineTTSEngineService
from app.services.provider_identity_service import ProviderIdentityService


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "gui" / "main.py"
PIPER_PROVIDER = ROOT / "app" / "providers" / "piper.py"
OFFLINE_SERVICE = ROOT / "app" / "services" / "offline_tts_engine_service.py"


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _service(
    tmp_path: Path,
    *,
    modules: set[str] | None = None,
    piper_executable: str | None = None,
) -> OfflineTTSEngineService:
    installed = modules or set()
    return OfflineTTSEngineService(
        _runtime(tmp_path),
        module_finder=lambda name: object() if name in installed else None,
        executable_finder=lambda name: piper_executable if name == "piper" else None,
    )


def _piper_voice(tmp_path: Path, name: str = "da_DK-talesyntese-medium") -> Path:
    model = tmp_path / "voices" / f"{name}.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"onnx-model")
    Path(f"{model}.json").write_text(
        json.dumps(
            {
                "dataset": "talesyntese",
                "language": {"code": "da_DK", "name_native": "Dansk"},
                "audio": {"sample_rate": 22050},
                "num_speakers": 1,
            }
        ),
        encoding="utf-8",
    )
    return model


def test_phase96_registry_exposes_existing_local_providers_without_new_generation_path(tmp_path: Path) -> None:
    service = _service(tmp_path)
    inventory = service.inventory(AppSettings(provider="mock"))
    assert [engine.engine_id for engine in inventory.engines] == ["piper", "kokoro"]
    assert [engine.provider_id for engine in inventory.engines] == ["piper", "kokoro"]
    source = PIPER_PROVIDER.read_text(encoding="utf-8")
    assert "shared_piper_runtime_service" in source
    assert "subprocess.Popen" in source
    assert "PiperVoice.load" not in source


def test_phase96_piper_python_runtime_and_voice_metadata_are_discovered(tmp_path: Path) -> None:
    model = _piper_voice(tmp_path)
    service = _service(tmp_path, modules={"piper"}, piper_executable="C:/Python/Scripts/piper.exe")
    snapshot = service.snapshot(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )
    assert snapshot.installed is True
    assert snapshot.module_available is True
    assert snapshot.runtime_mode == "python-api"
    assert snapshot.configured is True
    assert snapshot.ready is True
    assert snapshot.selected_voice_id == model.stem
    assert len(snapshot.voices) == 1
    voice = snapshot.voices[0]
    assert voice.selected is True
    assert voice.language_code == "da_DK"
    assert voice.sample_rate == 22050
    assert voice.speaker_count == 1
    assert voice.config_present is True


def test_phase96_piper_legacy_cli_is_visible_without_claiming_python_api(tmp_path: Path) -> None:
    model = _piper_voice(tmp_path)
    service = _service(tmp_path, piper_executable="C:/Python/Scripts/piper.exe")
    snapshot = service.snapshot(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )
    assert snapshot.installed is True
    assert snapshot.module_available is False
    assert snapshot.runtime_mode == "legacy-cli"
    assert snapshot.ready is True


def test_phase96_piper_requires_runtime_model_and_adjacent_config(tmp_path: Path) -> None:
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    service = _service(tmp_path, modules={"piper"})
    snapshot = service.snapshot(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )
    assert snapshot.installed is True
    assert snapshot.configured is False
    assert snapshot.ready is False
    assert any(".onnx.json" in issue for issue in snapshot.issues)


def test_phase96_missing_piper_runtime_is_reported_without_importing_it(tmp_path: Path) -> None:
    model = _piper_voice(tmp_path)
    service = _service(tmp_path)
    snapshot = service.snapshot(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )
    assert snapshot.installed is False
    assert snapshot.ready is False
    assert snapshot.state == "Runtime missing"
    assert any("runtime" in issue.casefold() for issue in snapshot.issues)


def test_phase96_discovers_known_piper_voice_root_and_deduplicates_selected_parent(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    model = runtime.app_root / "models" / "piper" / "voice.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"voice")
    Path(f"{model}.json").write_text("{}", encoding="utf-8")
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda name: object() if name == "piper" else None,
        executable_finder=lambda _name: None,
    )
    voices = service.discover_voices(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )
    assert len(voices) == 1
    assert voices[0].model_path == str(model.resolve())


def test_phase96_inventory_is_read_only_and_does_not_create_voice_directories(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    voice_root = runtime.data_dir / "offline-voices" / "piper"
    assert not voice_root.exists()
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda _name: None,
        executable_finder=lambda _name: None,
    )
    service.inventory(AppSettings(provider="mock"))
    assert not voice_root.exists()
    source = OFFLINE_SERVICE.read_text(encoding="utf-8")
    assert ".write_text(" not in source
    assert "subprocess" not in source


def test_phase96_kokoro_is_a_runtime_managed_engine(tmp_path: Path) -> None:
    service = _service(tmp_path, modules={"kokoro"})
    snapshot = service.snapshot("kokoro", AppSettings(provider="kokoro", voice_id="af_heart"))
    assert snapshot.installed is True
    assert snapshot.ready is True
    assert snapshot.runtime_mode == "python-api"
    assert snapshot.selected_voice_id == "af_heart"
    assert snapshot.voices == ()


def test_phase96_unknown_engine_is_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(KeyError):
        service.snapshot("unknown", AppSettings())


def test_phase96_service_is_injected_through_container_and_application_context(tmp_path: Path) -> None:
    container = create_service_container(_runtime(tmp_path))
    context = create_application_context(container)
    assert isinstance(container.offline_tts_engine_service, OfflineTTSEngineService)
    assert context.offline_tts_engine_service is container.offline_tts_engine_service


def test_phase96_dialog_lists_engines_and_explicitly_applies_piper_voice(qt_app, tmp_path: Path) -> None:
    model = _piper_voice(tmp_path)
    service = _service(tmp_path, modules={"piper"})
    settings = AppSettings(provider="piper", piper_model_path=str(model))
    applied: list[str] = []
    dialog = OfflineTTSEnginesDialog(
        service,
        lambda: settings,
        apply_piper_voice=applied.append,
        generation_active=lambda: False,
    )
    dialog.show()
    qt_app.processEvents()
    assert dialog.engine_table.rowCount() == 2
    assert dialog.voice_table.rowCount() == 1
    assert dialog.use_voice_button.isEnabled() is True
    dialog.use_selected_voice()
    assert applied == [str(model.resolve())]


def test_phase96_dialog_blocks_voice_changes_during_generation(qt_app, tmp_path: Path) -> None:
    model = _piper_voice(tmp_path)
    service = _service(tmp_path, modules={"piper"})
    dialog = OfflineTTSEnginesDialog(
        service,
        lambda: AppSettings(provider="piper", piper_model_path=str(model)),
        apply_piper_voice=lambda _path: None,
        generation_active=lambda: True,
    )
    dialog.show()
    qt_app.processEvents()
    assert dialog.use_voice_button.isEnabled() is False


def test_phase96_main_exposes_settings_shortcut_palette_and_safe_apply_path() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert "Offline TTS Engines" in source
    assert "Ctrl+Shift+L" in source
    assert "Provider: Offline TTS Engines" in source
    start = source.index("    def apply_offline_piper_voice")
    end = source.index("    def open_provider_accounts", start)
    segment = source[start:end]
    assert "self.provider.setCurrentText('piper')" in segment
    assert "self.piper.setText(str(path))" in segment
    assert "self.invalidate_preflight()" in segment
    assert ".start(" not in segment
    assert "retry" not in segment.casefold()


def test_phase96_piper_identity_points_to_current_ohf_project() -> None:
    identity = ProviderIdentityService().identity_for("piper")
    assert identity.help_url == "https://github.com/OHF-Voice/piper1-gpl"


def test_phase96_does_not_change_database_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase96-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
