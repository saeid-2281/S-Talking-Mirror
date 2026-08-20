from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import threading
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult
from app.providers.base import TTSProvider
from app.providers.piper_installation import resolve_piper_cli, resolve_piper_model_path
from app.providers.piper_runtime import (
    PiperRuntimeService,
    PiperRuntimeUnavailable,
    shared_piper_runtime_service,
)


def _hidden_windows_process_kwargs(
    *,
    platform_name: str | None = None,
) -> dict[str, object]:
    """Return a no-console Windows launch policy for Piper CLI subprocesses.

    S-Talking is a GUI application.  A console-subsystem executable such as
    Piper must not create or flash a terminal window for every generated row.
    The flags are applied only on Windows and do not change stdin/stdout/stderr,
    cancellation, timeout, provider/model/language authority, or synthesis.
    """

    if (platform_name or os.name) != "nt":
        return {}

    kwargs: dict[str, object] = {}
    # Use documented Win32 values as fallbacks as well.  This matters in frozen
    # GUI builds where a stripped/alternate subprocess module must still never
    # fall back to a visible console launch.
    no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) or 0x08000000)
    kwargs["creationflags"] = no_window

    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is not None:
        startupinfo = startupinfo_type()
        use_show_window = int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001) or 0x00000001)
        startupinfo.dwFlags |= use_show_window
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _kill_process(process: subprocess.Popen[str]) -> None:
    """Best-effort immediate termination used by user cancellation/timeouts."""

    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass


def _communicate_cancellable(
    process: subprocess.Popen[str],
    *,
    text: str,
    timeout_seconds: float,
    cancel_event: threading.Event,
) -> tuple[str, str]:
    """Wait for Piper in short slices so a Stop request is acted on promptly."""

    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    input_payload: str | None = text
    while True:
        if cancel_event.is_set():
            _kill_process(process)
            try:
                process.communicate(timeout=1.0)
            except Exception:
                pass
            raise ProviderError(
                "Generation cancelled by user.",
                provider_code="cancelled",
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _kill_process(process)
            try:
                process.communicate(timeout=1.0)
            except Exception:
                pass
            raise ProviderError(
                "Piper synthesis timed out.",
                retryable=True,
                provider_code="timeout",
            )

        try:
            return process.communicate(
                input=input_payload,
                timeout=min(0.20, remaining),
            )
        except subprocess.TimeoutExpired:
            # Python documents communicate() as safe to retry after TimeoutExpired.
            input_payload = None


class PiperProvider(TTSProvider):
    provider_id = "piper"
    display_name = "Piper"

    def __init__(
        self,
        settings: AppSettings,
        *,
        runtime: PiperRuntimeService | None = None,
        executable_finder=shutil.which,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self.settings = settings
        self.runtime = runtime or shared_piper_runtime_service()
        # Preserve the exact RuntimeConfig used to construct this provider.
        # Validation must resolve managed Portable paths against the same
        # runtime instead of falling back to the caller process runtime.
        self.runtime_config = runtime_config
        self.cli_invocation = resolve_piper_cli(
            self.runtime_config,
            executable_finder=executable_finder,
        )
        # Historical compatibility handle used by readiness/tests.  For the
        # managed Python-module fallback this points to python.exe while the
        # actual CLI prefix is stored in ``cli_invocation``.
        self.exe = self.cli_invocation.executable if self.cli_invocation is not None else None
        self._cancel_event = threading.Event()
        self._process_lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None

        if not settings.piper_model_path:
            raise ConfigurationError("Select a Piper .onnx model.")
        resolved_model = resolve_piper_model_path(settings.piper_model_path, self.runtime_config)
        self.model = resolved_model or Path(settings.piper_model_path).expanduser()
        if not self.model.is_file():
            raise ConfigurationError(f"Piper model not found: {self.model}")
        self.config = Path(f"{self.model}.json")
        if not self.config.is_file():
            raise ConfigurationError(f"Piper voice config not found: {self.config}")

        self.runtime_mode = "python-api" if self.runtime.api_available() else "legacy-cli"
        if self.runtime_mode == "legacy-cli" and self.cli_invocation is None:
            raise ConfigurationError(
                "Piper is not installed. Install the optional piper-tts runtime."
            )

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        self._cancel_event.clear()
        if self.runtime_mode == "python-api":
            try:
                return self.runtime.synthesize(
                    text,
                    self.model,
                    speed=settings.speed,
                    timeout_seconds=settings.timeout_seconds,
                    cancel_event=self._cancel_event,
                    requested_acceleration="auto",
                )
            except PiperRuntimeUnavailable:
                if self.cli_invocation is None:
                    raise
                self.runtime_mode = "legacy-cli"
        return self._synthesize_legacy_cli(text, settings)

    def _synthesize_legacy_cli(self, text: str, settings: AppSettings) -> bytes:
        if self.cli_invocation is None:
            raise ConfigurationError("Piper CLI is unavailable.")
        with tempfile.TemporaryDirectory(prefix="s_talking_piper_") as directory:
            output = Path(directory) / "out.wav"
            process = subprocess.Popen(
                self.cli_invocation.command(
                    "--model",
                    str(self.model),
                    "--output_file",
                    str(output),
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=str(Path(self.cli_invocation.executable).resolve().parent),
                **_hidden_windows_process_kwargs(),
            )
            with self._process_lock:
                self._process = process
            try:
                _stdout, stderr = _communicate_cancellable(
                    process,
                    text=text,
                    timeout_seconds=settings.timeout_seconds,
                    cancel_event=self._cancel_event,
                )
            finally:
                with self._process_lock:
                    if self._process is process:
                        self._process = None

            if self._cancel_event.is_set():
                raise ProviderError(
                    "Generation cancelled by user.",
                    provider_code="cancelled",
                )
            if process.returncode or not output.exists():
                executable = str(self.cli_invocation.executable)
                detail = (stderr or "Piper produced no output file").strip()
                raise ProviderError(
                    f"Piper CLI failed (exit={process.returncode}, executable={executable}): {detail}"[:800],
                    provider_code="piper_cli_error",
                )
            return output.read_bytes()

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._process_lock:
            process = self._process
        if process is not None:
            _kill_process(process)

    def close(self) -> None:
        self.cancel()
        with self._process_lock:
            self._process = None

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.piper_model_path:
            return ProviderConfigurationResult(False, "Select a Piper .onnx model.")
        model = resolve_piper_model_path(settings.piper_model_path, self.runtime_config)
        model = model or Path(settings.piper_model_path).expanduser()
        if not model.is_file():
            return ProviderConfigurationResult(False, f"Piper model not found: {model}")
        config = Path(f"{model}.json")
        if not config.is_file():
            return ProviderConfigurationResult(False, f"Piper voice config not found: {config}")
        if not self.runtime.api_available() and self.cli_invocation is None:
            return ProviderConfigurationResult(
                False,
                "Piper runtime is unavailable.",
                missing_dependency="piper-tts",
            )
        mode = "persistent Python runtime" if self.runtime.api_available() else "legacy CLI fallback"
        return ProviderConfigurationResult(True, f"Piper is ready via {mode}.")

    def test_connection(self) -> ProviderConfigurationResult:
        validation = self.validate_configuration(self.settings)
        if not validation.ok:
            return validation
        if self.runtime.api_available():
            try:
                health = self.runtime.warm(self.model, requested_acceleration="auto")
            except Exception as exc:
                return ProviderConfigurationResult(False, f"Piper runtime warm-up failed: {exc}")
            return ProviderConfigurationResult(
                True,
                f"Piper runtime loaded on {health.resolved_acceleration.upper()}.",
            )
        return ProviderConfigurationResult(True, "Piper legacy CLI fallback is available.")

    def list_voices(self) -> list[dict]:
        return [
            {
                "voice_id": str(self.model),
                "name": self.model.stem,
                "category": "offline",
            }
        ]

    def list_models(self) -> list[dict]:
        return [{"model_id": "piper-local", "name": "Piper local ONNX"}]

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            "piper",
            "Piper",
            remote=False,
            requires_credential=False,
            supports_voice_listing=True,
            supports_model_listing=True,
            supports_language_code=True,
            supports_speed=True,
            supports_streaming=True,
            supports_cancellation=True,
            supported_output_formats=("wav",),
            optional_dependency="piper-tts",
        )
