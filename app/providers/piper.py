from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult
from app.providers.base import TTSProvider
from app.providers.piper_installation import resolve_piper_executable
from app.providers.piper_runtime import (
    PiperRuntimeService,
    PiperRuntimeUnavailable,
    shared_piper_runtime_service,
)


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
        self.exe = resolve_piper_executable(
            runtime_config,
            executable_finder=executable_finder,
        )
        self._cancel_event = threading.Event()
        self._process_lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None

        if not settings.piper_model_path:
            raise ConfigurationError("Select a Piper .onnx model.")
        self.model = Path(settings.piper_model_path).expanduser()
        if not self.model.is_file():
            raise ConfigurationError(f"Piper model not found: {self.model}")
        self.config = Path(f"{self.model}.json")
        if not self.config.is_file():
            raise ConfigurationError(f"Piper voice config not found: {self.config}")

        self.runtime_mode = "python-api" if self.runtime.api_available() else "legacy-cli"
        if self.runtime_mode == "legacy-cli" and not self.exe:
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
                if not self.exe:
                    raise
                self.runtime_mode = "legacy-cli"
        return self._synthesize_legacy_cli(text, settings)

    def _synthesize_legacy_cli(self, text: str, settings: AppSettings) -> bytes:
        if not self.exe:
            raise ConfigurationError("Piper CLI is unavailable.")
        with tempfile.TemporaryDirectory(prefix="s_talking_piper_") as directory:
            output = Path(directory) / "out.wav"
            process = subprocess.Popen(
                [
                    self.exe,
                    "--model",
                    str(self.model),
                    "--output_file",
                    str(output),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            with self._process_lock:
                self._process = process
            try:
                _stdout, stderr = process.communicate(
                    input=text,
                    timeout=settings.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise ProviderError(
                    "Piper synthesis timed out.",
                    retryable=True,
                    provider_code="timeout",
                ) from exc
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
                raise ProviderError(
                    (stderr or "Piper failed")[:800],
                    provider_code="piper_cli_error",
                )
            return output.read_bytes()

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def close(self) -> None:
        with self._process_lock:
            self._process = None

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.piper_model_path:
            return ProviderConfigurationResult(False, "Select a Piper .onnx model.")
        model = Path(settings.piper_model_path).expanduser()
        if not model.is_file():
            return ProviderConfigurationResult(False, f"Piper model not found: {model}")
        config = Path(f"{model}.json")
        if not config.is_file():
            return ProviderConfigurationResult(False, f"Piper voice config not found: {config}")
        if not self.runtime.api_available() and not self.exe:
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
