from __future__ import annotations

import importlib
import importlib.util
import io
import threading
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.exceptions import ConfigurationError, ProviderError
from app.models.piper_runtime import PiperAccelerationDecision, PiperRuntimeHealth


class PiperRuntimeUnavailable(ConfigurationError):
    """Raised when the in-process Piper Python runtime cannot be used."""


@dataclass
class _RuntimeSlot:
    model_path: Path
    resolved_acceleration: str
    voice: object
    lock: threading.RLock = field(default_factory=threading.RLock)
    load_count: int = 1
    synthesis_count: int = 0
    last_error: str | None = None


class PiperRuntimeService:
    """Process-local Piper model cache with cooperative cancellation.

    The service intentionally owns only in-process model lifecycle. It does not
    download voices, alter settings, create a local HTTP server, or bypass the
    normal S-Talking generation/preflight flow.
    """

    def __init__(
        self,
        *,
        piper_loader: Callable[[], object] | None = None,
        execution_provider_loader: Callable[[], tuple[str, ...]] | None = None,
        max_cache_entries: int = 2,
    ) -> None:
        self._custom_piper_loader = piper_loader is not None
        self._piper_loader = piper_loader or self._import_piper
        self._execution_provider_loader = (
            execution_provider_loader or self._available_execution_providers
        )
        self.max_cache_entries = max(1, int(max_cache_entries))
        self._cache: OrderedDict[tuple[str, str], _RuntimeSlot] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._load_count = 0
        self._synthesis_count = 0
        self._last_error: str | None = None
        self._fallback_reason: str | None = None
        self._cuda_disabled_reason: str | None = None

    @staticmethod
    def python_api_available() -> bool:
        try:
            return importlib.util.find_spec("piper") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def api_available(self) -> bool:
        if not self._custom_piper_loader:
            return self.python_api_available()
        try:
            module = self._piper_loader()
        except (ImportError, ModuleNotFoundError):
            return False
        voice_class = getattr(module, "PiperVoice", None)
        return voice_class is not None and callable(getattr(voice_class, "load", None))

    def acceleration(self, requested: str = "auto") -> PiperAccelerationDecision:
        normalized = str(requested or "auto").strip().casefold()
        if normalized not in {"auto", "cpu", "cuda"}:
            normalized = "auto"
        providers = {item.casefold() for item in self._safe_execution_providers()}
        cuda_available = "cudaexecutionprovider" in providers
        auto_cuda_available = cuda_available and self._cuda_disabled_reason is None
        if normalized == "cpu":
            return PiperAccelerationDecision(
                requested="cpu",
                resolved="cpu",
                cuda_available=cuda_available,
                detail="CPU was explicitly requested.",
            )
        if normalized == "cuda":
            if not cuda_available:
                return PiperAccelerationDecision(
                    requested="cuda",
                    resolved="cpu",
                    cuda_available=False,
                    detail="CUDA was requested but ONNX Runtime does not expose CUDA; CPU will be used.",
                )
            return PiperAccelerationDecision(
                requested="cuda",
                resolved="cuda",
                cuda_available=True,
                detail="CUDAExecutionProvider is available.",
            )
        return PiperAccelerationDecision(
            requested="auto",
            resolved="cuda" if auto_cuda_available else "cpu",
            cuda_available=cuda_available,
            detail=(
                "Auto selected CUDAExecutionProvider."
                if auto_cuda_available
                else (
                    f"Auto selected CPU after CUDA warm-up failed: {self._cuda_disabled_reason}"
                    if self._cuda_disabled_reason
                    else "Auto selected CPU because CUDAExecutionProvider is unavailable."
                )
            ),
        )

    def warm(self, model_path: str | Path, *, requested_acceleration: str = "auto") -> PiperRuntimeHealth:
        model = self._validate_model(model_path)
        decision = self.acceleration(requested_acceleration)
        self._slot(model, decision)
        return self.health(model, requested_acceleration=requested_acceleration)

    def synthesize(
        self,
        text: str,
        model_path: str | Path,
        *,
        speed: float = 1.0,
        timeout_seconds: float = 90.0,
        cancel_event: threading.Event | None = None,
        requested_acceleration: str = "auto",
    ) -> bytes:
        model = self._validate_model(model_path)
        decision = self.acceleration(requested_acceleration)
        slot = self._slot(model, decision)
        started = time.monotonic()
        cancel_event = cancel_event or threading.Event()

        with slot.lock:
            if cancel_event.is_set():
                raise ProviderError(
                    "Generation cancelled by user.",
                    provider_code="cancelled",
                )
            try:
                payload = self._synthesize_locked(
                    slot.voice,
                    text,
                    speed=speed,
                    timeout_seconds=timeout_seconds,
                    cancel_event=cancel_event,
                    started=started,
                )
            except ProviderError:
                raise
            except Exception as exc:
                message = self._safe_error(exc)
                slot.last_error = message
                self._last_error = message
                raise ProviderError(
                    f"Piper runtime failed: {message}",
                    provider_code="piper_runtime_error",
                    technical_details=message,
                ) from exc
            slot.synthesis_count += 1
            self._synthesis_count += 1
            slot.last_error = None
            self._last_error = None
            return payload

    def restart(self, model_path: str | Path | None = None) -> int:
        with self._cache_lock:
            self._cuda_disabled_reason = None
            self._fallback_reason = None
            self._last_error = None
            if model_path is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            key_path = self._path_key(Path(model_path).expanduser())
            keys = [key for key in self._cache if key[0] == key_path]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def health(
        self,
        model_path: str | Path | None = None,
        *,
        requested_acceleration: str = "auto",
    ) -> PiperRuntimeHealth:
        decision = self.acceleration(requested_acceleration)
        target = Path(model_path).expanduser() if model_path else None
        key_path = self._path_key(target) if target else None
        with self._cache_lock:
            matching = [
                slot
                for (path_key, _acceleration), slot in self._cache.items()
                if key_path is not None and path_key == key_path
            ]
            loaded = bool(matching)
            resolved = matching[-1].resolved_acceleration if matching else decision.resolved
            last_error = matching[-1].last_error if matching and matching[-1].last_error else self._last_error
            return PiperRuntimeHealth(
                available=self.api_available(),
                model_path=str(target.resolve()) if target else None,
                loaded=loaded,
                requested_acceleration=decision.requested,
                resolved_acceleration=resolved,
                cuda_available=decision.cuda_available,
                cache_entries=len(self._cache),
                load_count=self._load_count,
                synthesis_count=self._synthesis_count,
                last_error=last_error,
                fallback_reason=self._fallback_reason,
            )

    def _slot(self, model: Path, decision: PiperAccelerationDecision) -> _RuntimeSlot:
        key = (self._path_key(model), decision.resolved)
        with self._cache_lock:
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing

            module = self._load_piper_module()
            voice_class = getattr(module, "PiperVoice", None)
            if voice_class is None or not callable(getattr(voice_class, "load", None)):
                raise PiperRuntimeUnavailable("Installed Piper package does not expose PiperVoice.load().")

            resolved = decision.resolved
            try:
                voice = voice_class.load(str(model), use_cuda=resolved == "cuda")
            except Exception as exc:
                if decision.requested == "auto" and resolved == "cuda":
                    self._cuda_disabled_reason = self._safe_error(exc)
                    self._fallback_reason = (
                        f"CUDA model load failed; Auto fell back to CPU: {self._cuda_disabled_reason}"
                    )
                    resolved = "cpu"
                    key = (self._path_key(model), resolved)
                    existing = self._cache.get(key)
                    if existing is not None:
                        self._cache.move_to_end(key)
                        return existing
                    try:
                        voice = voice_class.load(str(model), use_cuda=False)
                    except Exception as cpu_exc:
                        self._last_error = self._safe_error(cpu_exc)
                        raise ProviderError(
                            f"Piper model could not be loaded: {self._last_error}",
                            provider_code="piper_model_load_failed",
                            technical_details=self._last_error,
                        ) from cpu_exc
                else:
                    self._last_error = self._safe_error(exc)
                    raise ProviderError(
                        f"Piper model could not be loaded: {self._last_error}",
                        provider_code="piper_model_load_failed",
                        technical_details=self._last_error,
                    ) from exc

            slot = _RuntimeSlot(model, resolved, voice)
            self._cache[key] = slot
            self._cache.move_to_end(key)
            self._load_count += 1
            self._evict_if_needed(exclude=key)
            self._last_error = None
            return slot

    def _synthesize_locked(
        self,
        voice: object,
        text: str,
        *,
        speed: float,
        timeout_seconds: float,
        cancel_event: threading.Event,
        started: float,
    ) -> bytes:
        module = self._load_piper_module()
        config_class = getattr(module, "SynthesisConfig", None)
        speed_value = max(0.01, float(speed or 1.0))
        kwargs: dict[str, object] = {}
        if config_class is not None:
            kwargs["syn_config"] = config_class(length_scale=1.0 / speed_value)

        synthesize = getattr(voice, "synthesize", None)
        if not callable(synthesize):
            return self._synthesize_wav_compat(
                voice,
                text,
                kwargs=kwargs,
                timeout_seconds=timeout_seconds,
                cancel_event=cancel_event,
                started=started,
            )

        output = io.BytesIO()
        chunks = synthesize(text, **kwargs)
        wrote_audio = False
        with wave.open(output, "wb") as wav_file:
            for chunk in chunks:
                self._check_interrupt(cancel_event, timeout_seconds, started)
                if not wrote_audio:
                    wav_file.setframerate(int(getattr(chunk, "sample_rate")))
                    wav_file.setsampwidth(int(getattr(chunk, "sample_width")))
                    wav_file.setnchannels(int(getattr(chunk, "sample_channels")))
                audio = bytes(getattr(chunk, "audio_int16_bytes"))
                if audio:
                    wav_file.writeframes(audio)
                    wrote_audio = True
        self._check_interrupt(cancel_event, timeout_seconds, started)
        if not wrote_audio:
            raise ProviderError(
                "Piper returned no audio.",
                provider_code="piper_empty_audio",
            )
        return output.getvalue()

    def _synthesize_wav_compat(
        self,
        voice: object,
        text: str,
        *,
        kwargs: dict[str, object],
        timeout_seconds: float,
        cancel_event: threading.Event,
        started: float,
    ) -> bytes:
        synthesize_wav = getattr(voice, "synthesize_wav", None)
        if not callable(synthesize_wav):
            raise PiperRuntimeUnavailable("Installed Piper package exposes no supported synthesis API.")
        self._check_interrupt(cancel_event, timeout_seconds, started)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            synthesize_wav(text, wav_file, **kwargs)
        self._check_interrupt(cancel_event, timeout_seconds, started)
        return output.getvalue()

    def _load_piper_module(self) -> object:
        try:
            return self._piper_loader()
        except (ImportError, ModuleNotFoundError) as exc:
            raise PiperRuntimeUnavailable(
                "Piper Python API is unavailable. Install the optional piper-tts runtime."
            ) from exc

    @staticmethod
    def _validate_model(model_path: str | Path) -> Path:
        model = Path(model_path).expanduser()
        if not model.is_file() or model.suffix.casefold() != ".onnx":
            raise ConfigurationError(f"Piper model not found: {model}")
        config = Path(f"{model}.json")
        if not config.is_file():
            raise ConfigurationError(f"Piper voice config not found: {config}")
        return model

    @staticmethod
    def _check_interrupt(
        cancel_event: threading.Event,
        timeout_seconds: float,
        started: float,
    ) -> None:
        if cancel_event.is_set():
            raise ProviderError(
                "Generation cancelled by user.",
                provider_code="cancelled",
            )
        if timeout_seconds > 0 and (time.monotonic() - started) > timeout_seconds:
            raise ProviderError(
                "Piper synthesis timed out.",
                retryable=True,
                provider_code="timeout",
            )

    def _evict_if_needed(self, *, exclude: tuple[str, str]) -> None:
        while len(self._cache) > self.max_cache_entries:
            key = next(iter(self._cache))
            if key == exclude and len(self._cache) > 1:
                key = list(self._cache.keys())[1]
            self._cache.pop(key, None)

    def _safe_execution_providers(self) -> tuple[str, ...]:
        try:
            return tuple(self._execution_provider_loader())
        except Exception:
            return ()

    @staticmethod
    def _available_execution_providers() -> tuple[str, ...]:
        try:
            module = importlib.import_module("onnxruntime")
            provider_getter = getattr(module, "get_available_providers", None)
            if callable(provider_getter):
                return tuple(str(item) for item in provider_getter())
        except (ImportError, ModuleNotFoundError):
            pass
        return ()

    @staticmethod
    def _import_piper() -> object:
        return importlib.import_module("piper")

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except OSError:
            return str(path.absolute()).casefold()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:800]


_SHARED_RUNTIME = PiperRuntimeService()


def shared_piper_runtime_service() -> PiperRuntimeService:
    return _SHARED_RUNTIME
