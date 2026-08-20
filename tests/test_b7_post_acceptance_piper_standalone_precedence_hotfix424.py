from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.providers.piper_installation import (
    managed_piper_executable_candidates,
    resolve_piper_cli,
)


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def test_h424_official_standalone_precedes_copied_venv_wrapper(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    root = runtime.data_dir.parent / "local-engines" / "piper"
    wrapper = root / ".venv" / "Scripts" / "piper.exe"
    standalone = root / "bin" / "piper.exe"

    wrapper.parent.mkdir(parents=True, exist_ok=True)
    standalone.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_bytes(b"copied-stale-wrapper")
    standalone.write_bytes(b"verified-official-standalone")

    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == standalone.resolve()
    assert Path(invocation.executable).resolve() != wrapper.resolve()


def test_h424_historical_inventory_order_keeps_wrapper_but_runtime_fallback_still_works(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    root = runtime.data_dir.parent / "local-engines" / "piper"
    wrapper = root / ".venv" / "Scripts" / "piper.exe"

    # Historical H2 inventory contract remains stable.
    assert managed_piper_executable_candidates(runtime)[0] == wrapper

    # If the preferred standalone runtime is absent, the wrapper still works
    # as the next managed fallback.
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_bytes(b"legacy-wrapper")
    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == wrapper.resolve()


def test_h424_explicit_override_still_has_highest_authority(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = _runtime(tmp_path)
    root = runtime.data_dir.parent / "local-engines" / "piper"
    standalone = root / "bin" / "piper.exe"
    explicit = tmp_path / "explicit-piper.exe"
    standalone.parent.mkdir(parents=True, exist_ok=True)
    standalone.write_bytes(b"standalone")
    explicit.write_bytes(b"explicit")
    monkeypatch.setenv("S_TALKING_PIPER_EXECUTABLE", str(explicit))

    invocation = resolve_piper_cli(runtime, executable_finder=lambda _name: None)

    assert invocation is not None
    assert Path(invocation.executable).resolve() == explicit.resolve()
