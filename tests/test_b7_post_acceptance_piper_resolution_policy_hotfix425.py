from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.providers.piper_installation import (
    _managed_piper_resolution_candidates,
    managed_piper_executable_candidates,
    resolve_piper_cli,
)


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def test_h425_h2_inventory_contract_and_runtime_policy_are_deliberately_separate(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    root = runtime.data_dir.parent / "local-engines" / "piper"
    wrapper = root / ".venv" / "Scripts" / "piper.exe"
    standalone = root / "bin" / "piper.exe"

    assert managed_piper_executable_candidates(runtime)[0] == wrapper
    assert _managed_piper_resolution_candidates(runtime)[0] == standalone


def test_h425_runtime_resolver_prefers_official_standalone_when_both_exist(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    root = runtime.data_dir.parent / "local-engines" / "piper"
    wrapper = root / ".venv" / "Scripts" / "piper.exe"
    standalone = root / "bin" / "piper.exe"

    wrapper.parent.mkdir(parents=True, exist_ok=True)
    standalone.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_bytes(b"stale-copied-wrapper")
    standalone.write_bytes(b"verified-official-standalone")

    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == standalone.resolve()


def test_h425_wrapper_remains_fallback_when_standalone_is_absent(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    root = runtime.data_dir.parent / "local-engines" / "piper"
    wrapper = root / ".venv" / "Scripts" / "piper.exe"

    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_bytes(b"legacy-wrapper")

    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == wrapper.resolve()
