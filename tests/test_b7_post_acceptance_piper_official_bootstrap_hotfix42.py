from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.providers.piper_installation import resolve_piper_cli


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"
INSTALLATION = ROOT / "app" / "providers" / "piper_installation.py"


def test_h42_resolver_accepts_official_standalone_windows_layout(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    standalone = runtime.data_dir.parent / "local-engines" / "piper" / "bin" / "piper.exe"
    standalone.parent.mkdir(parents=True, exist_ok=True)
    standalone.write_bytes(b"standalone")

    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == standalone.resolve()
    assert invocation.prefix_args == ()
    assert invocation.launch_mode == "console-script"


def test_h42_migration_supports_explicit_official_standalone_bootstrap() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "BootstrapPiperRuntimeRoot" in source
    assert 'local-engines\\piper\\bin' in source
    assert "Official standalone Piper runtime" in source
    assert "PiperStandaloneExe" in source
    assert "StandalonePresent" in source
    assert "no runnable console wrapper, standalone binary, or managed Python-module fallback" in source


def test_h42_migration_no_longer_requires_duplicate_model_under_engine_root() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'ManagedModel = Join-Path $DestinationRuntimeData "offline-voices\\piper\\da_DK-talesyntese-medium\\da_DK-talesyntese-medium.onnx"' in source
    assert 'local-engines\\piper\\voices\\da_DK-talesyntese-medium.onnx' not in source


def test_h42_standalone_candidate_is_central_runtime_authority() -> None:
    source = INSTALLATION.read_text(encoding="utf-8")

    assert 'root / "bin" / "piper.exe"' in source
    assert "resolve_piper_cli" in source
