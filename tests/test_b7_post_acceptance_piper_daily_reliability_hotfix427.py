from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.config.runtime import RuntimeConfig
from app.gui.main import MainWindow
from app.gui.worker import GenerationWorker
from app.models import AppSettings
from app.providers.piper import (
    PiperProvider,
    _hidden_windows_process_kwargs,
)


class _FakeSettingsStore:
    values: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def value(self, key: str, default=None):
        return self.values.get(key, default)


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _FakeProvider:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def test_h427_project_restore_uses_container_runtime_not_missing_context_runtime(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    current = (
        runtime.data_dir
        / "offline-voices"
        / "piper"
        / "voice"
        / "voice.onnx"
    )
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_bytes(b"model")

    stale = (
        Path(r"C:\ST Wpro\S-Talking-B7-OLD-Portable-Windows-x64")
        / "S-Talking-Data"
        / "data"
        / "offline-voices"
        / "piper"
        / "voice"
        / "voice.onnx"
    )
    fake_window = SimpleNamespace(
        context=SimpleNamespace(container=SimpleNamespace(runtime=runtime))
    )

    resolved = MainWindow.resolved_piper_model_text(fake_window, str(stale))

    assert Path(resolved).resolve() == current.resolve()
    source = Path(__import__("app.gui.main", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "self.context.runtime" not in source


def test_h427_global_preferences_persist_piper_model_path(monkeypatch) -> None:
    import app.gui.main as main_module

    _FakeSettingsStore.values = {}
    monkeypatch.setattr(main_module, "QSettings", _FakeSettingsStore)
    settings = AppSettings(
        provider="piper",
        piper_model_path=r"C:\voices\da.onnx",
    )
    fake_window = SimpleNamespace()

    MainWindow.save_global_preferences(fake_window, settings)
    loaded = MainWindow.load_global_preferences(
        fake_window,
        AppSettings(provider="mock"),
    )

    assert _FakeSettingsStore.values["global_settings/piper_model_path"] == r"C:\voices\da.onnx"
    assert loaded.piper_model_path == r"C:\voices\da.onnx"


def test_h427_windows_hidden_policy_has_literal_fallback(monkeypatch) -> None:
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", None, raising=False)

    kwargs = _hidden_windows_process_kwargs(platform_name="nt")

    assert kwargs["creationflags"] == 0x08000000


def test_h427_piper_cancel_kills_active_process_immediately(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    model = runtime.data_dir / "offline-voices" / "piper" / "voice" / "voice.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"model")
    Path(f"{model}.json").write_text("{}", encoding="utf-8")

    standalone = runtime.data_dir.parent / "local-engines" / "piper" / "bin" / "piper.exe"
    standalone.parent.mkdir(parents=True, exist_ok=True)
    standalone.write_bytes(b"exe")

    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=str(model)),
        runtime_config=runtime,
        executable_finder=lambda _name: None,
    )
    process = _FakeProcess()
    provider._process = process

    provider.cancel()

    assert provider._cancel_event.is_set()
    assert process.killed is True


def test_h427_worker_stop_calls_provider_cancel_and_is_immediate(tmp_path: Path) -> None:
    worker = GenerationWorker(
        [],
        AppSettings(provider="piper"),
        tmp_path / "out",
        tmp_path / "jobs.sqlite3",
        "project",
    )
    provider = _FakeProvider()
    worker._provider = provider

    worker.stop()

    assert worker.stop_requested is True
    assert provider.cancelled is True


def test_h427_manual_stop_copy_no_longer_promises_wait_for_current_request() -> None:
    main_source = Path(__import__("app.gui.main", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    worker_source = Path(__import__("app.gui.worker", fromlist=["x"]).__file__).read_text(encoding="utf-8")

    assert "Waiting for the current provider request" not in main_source
    assert "Stopping after the current provider request" not in main_source
    assert "Finishing the current provider request" not in worker_source
    assert "Cancelling the active provider request now" in main_source
    assert "Cancelling the active provider request now" in worker_source


def test_h427_piper_cli_failure_includes_executable_and_exit_diagnostics() -> None:
    source = Path(__import__("app.providers.piper", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "Piper CLI failed (exit=" in source
    assert "executable=" in source
    assert "CREATE_NEW_CONSOLE" not in source
