from __future__ import annotations

import subprocess
from pathlib import Path

import app.providers.piper as piper_module
from app.config.runtime import RuntimeConfig
from app.models import AppSettings
from app.providers.piper import PiperProvider, _hidden_windows_process_kwargs


class _FakeStartupInfo:
    def __init__(self) -> None:
        self.dwFlags = 0
        self.wShowWindow = -1


class _LegacyOnlyRuntime:
    def api_available(self) -> bool:
        return False


class _FakePopen:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def __init__(self, command: list[str], **kwargs: object) -> None:
        self.command = command
        self.kwargs = kwargs
        self.returncode = 0
        self._output = Path(command[command.index("--output_file") + 1])
        self.__class__.calls.append((command, kwargs))

    def communicate(self, input: str | None = None, timeout: float | None = None):
        del input, timeout
        self._output.write_bytes(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 64)
        return "", ""

    def kill(self) -> None:
        self.returncode = -9

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15


def test_h426_windows_launch_policy_hides_console(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)

    kwargs = _hidden_windows_process_kwargs(platform_name="nt")

    assert kwargs["creationflags"] == 0x08000000
    startupinfo = kwargs["startupinfo"]
    assert isinstance(startupinfo, _FakeStartupInfo)
    assert startupinfo.dwFlags & 0x00000001
    assert startupinfo.wShowWindow == 0


def test_h426_non_windows_launch_policy_is_unchanged() -> None:
    assert _hidden_windows_process_kwargs(platform_name="posix") == {}


def test_h426_one_provider_synthesis_has_one_direct_popen_and_uses_launch_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()

    model = runtime.data_dir / "offline-voices" / "piper" / "voice" / "voice.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"model")
    Path(f"{model}.json").write_text("{}", encoding="utf-8")

    standalone = runtime.data_dir.parent / "local-engines" / "piper" / "bin" / "piper.exe"
    standalone.parent.mkdir(parents=True, exist_ok=True)
    standalone.write_bytes(b"fake-piper")

    settings = AppSettings(provider="piper", piper_model_path=str(model), speed=1.0)
    provider = PiperProvider(
        settings,
        runtime=_LegacyOnlyRuntime(),
        runtime_config=runtime,
        executable_finder=lambda _name: None,
    )

    _FakePopen.calls.clear()
    monkeypatch.setattr(piper_module.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(
        piper_module,
        "_hidden_windows_process_kwargs",
        lambda: {"creationflags": 0x08000000, "startupinfo": "hidden"},
    )

    audio = provider.synthesize("Hej.", settings)

    assert audio.startswith(b"RIFF")
    assert len(_FakePopen.calls) == 1
    command, kwargs = _FakePopen.calls[0]
    assert command[0] == str(standalone.resolve())
    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"] == "hidden"
    assert "shell" not in kwargs


def test_h426_source_does_not_request_new_console() -> None:
    source = Path(piper_module.__file__).read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in source
    assert "STARTF_USESHOWWINDOW" in source
    assert "SW_HIDE" in source
    assert "CREATE_NEW_CONSOLE" not in source
