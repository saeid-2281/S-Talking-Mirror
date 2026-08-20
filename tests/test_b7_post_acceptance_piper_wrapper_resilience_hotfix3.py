from __future__ import annotations

import json
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models import AppSettings
from app.providers.piper import PiperProvider
from app.providers.piper_installation import (
    resolve_piper_cli,
    resolve_piper_executable,
)
from app.services.offline_tts_engine_service import OfflineTTSEngineService


ROOT = Path(__file__).resolve().parents[1]
FROZEN_MAIN = ROOT / "app" / "frozen_main.py"
MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"
READINESS = ROOT / "app" / "services" / "provider_readiness_service.py"
RELEASE = ROOT / "app" / "services" / "release_readiness_service.py"
PROVIDER = ROOT / "app" / "providers" / "piper.py"


class _NoPythonPiperRuntime:
    @staticmethod
    def api_available() -> bool:
        return False


def _managed_python_module_runtime(tmp_path: Path) -> tuple[RuntimeConfig, Path, Path]:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    engine = runtime.data_dir.parent / "local-engines" / "piper"
    python = engine / ".venv" / "Scripts" / "python.exe"
    module = engine / ".venv" / "Lib" / "site-packages" / "piper" / "__main__.py"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"stub-python")
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("def main(): pass\n", encoding="utf-8")

    model = (
        runtime.data_dir.parent
        / "offline-voices"
        / "piper"
        / "da_DK-talesyntese-medium"
        / "da_DK-talesyntese-medium.onnx"
    )
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"onnx")
    Path(f"{model}.json").write_text(
        json.dumps({"language": {"code": "da_DK"}, "audio": {"sample_rate": 22050}}),
        encoding="utf-8",
    )
    return runtime, python, model


def test_h3_resolver_uses_managed_python_module_when_piper_wrapper_is_absent(tmp_path: Path) -> None:
    runtime, python, _model = _managed_python_module_runtime(tmp_path)

    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == python.resolve()
    assert invocation.prefix_args == ("-m", "piper")
    assert invocation.launch_mode == "python-module"
    assert invocation.command("--help") == [str(python.resolve()), "-m", "piper", "--help"]
    assert Path(resolve_piper_executable(runtime, executable_finder=lambda _name: None) or "").resolve() == python.resolve()


def test_h3_offline_inventory_recognizes_python_module_fallback_without_wrapper(tmp_path: Path) -> None:
    runtime, python, model = _managed_python_module_runtime(tmp_path)
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda _name: None,
        executable_finder=lambda _name: None,
    )

    snapshot = service.snapshot(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )

    assert snapshot.installed is True
    assert snapshot.runtime_mode == "legacy-cli"
    assert Path(snapshot.executable_path or "").resolve() == python.resolve()
    assert snapshot.ready is True


def test_h3_provider_legacy_cli_uses_python_module_prefix_when_wrapper_is_absent(tmp_path: Path) -> None:
    runtime, python, model = _managed_python_module_runtime(tmp_path)
    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=str(model)),
        runtime=_NoPythonPiperRuntime(),
        runtime_config=runtime,
        executable_finder=lambda _name: None,
    )

    assert provider.runtime_mode == "legacy-cli"
    assert provider.cli_invocation is not None
    assert provider.cli_invocation.launch_mode == "python-module"
    assert provider.cli_invocation.command("--help") == [
        str(python.resolve()),
        "-m",
        "piper",
        "--help",
    ]
    assert provider.validate_configuration(provider.settings).ok is True


def test_h3_all_piper_readiness_surfaces_use_central_resolver() -> None:
    readiness = READINESS.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    provider = PROVIDER.read_text(encoding="utf-8")

    assert "resolve_piper_executable" in readiness
    assert 'return bool(resolve_piper_executable(executable_finder=shutil.which))' in readiness
    assert "resolve_piper_executable(" in release
    assert "self.runtime" in release
    assert "resolve_piper_cli" in provider
    assert "self.cli_invocation.command(" in provider


def test_h3_migration_no_longer_requires_pip_console_wrapper() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "PiperPython" in source
    assert "PiperModule" in source
    assert "PythonModuleFallbackPresent" in source
    assert "neither the console wrapper nor the managed Python-module fallback" in source
    assert "LOCAL_ENGINES_PIPER_CLI_PROBE=1" in source


def test_h3_frozen_verifier_actively_probes_resolved_cli_without_synthesis() -> None:
    source = FROZEN_MAIN.read_text(encoding="utf-8")
    handler = source.split("def _handle_local_engines_runtime_verify", 1)[1].split(
        "def _handle_provider_accounts_runtime_verify", 1
    )[0]

    assert "resolve_piper_cli(runtime)" in handler
    assert 'cli_invocation.command("--help")' in handler
    assert "LOCAL_ENGINES_PIPER_CLI_LAUNCH_MODE" in handler
    assert "LOCAL_ENGINES_PIPER_CLI_PROBE" in handler
    assert "subprocess.run(" in handler
    assert ".synthesize(" not in handler
    assert ".warm(" not in handler
