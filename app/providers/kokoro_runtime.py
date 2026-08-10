from __future__ import annotations

import importlib
import importlib.util
import io
import math
import struct
import threading
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from app.exceptions import ConfigurationError, ProviderError


@dataclass(frozen=True)
class KokoroLanguageSpec:
    language_code: str
    pipeline_code: str
    display_name: str
    voice_prefixes: tuple[str, ...]
    optional_extra: str | None = None


@dataclass(frozen=True)
class KokoroVoiceSpec:
    voice_id: str
    language_code: str
    display_name: str


@dataclass(frozen=True)
class KokoroRuntimeHealth:
    available: bool
    loaded_language_codes: tuple[str, ...]
    pipeline_count: int
    load_count: int
    synthesis_count: int
    last_error: str | None = None


@dataclass
class _PipelineSlot:
    language: KokoroLanguageSpec
    pipeline: object
    lock: threading.RLock = field(default_factory=threading.RLock)
    synthesis_count: int = 0
    last_error: str | None = None


KOKORO_LANGUAGES: tuple[KokoroLanguageSpec, ...] = (
    KokoroLanguageSpec("en-US", "a", "American English", ("af_", "am_")),
    KokoroLanguageSpec("en-GB", "b", "British English", ("bf_", "bm_")),
    KokoroLanguageSpec("es", "e", "Spanish", ("ef_", "em_")),
    KokoroLanguageSpec("fr-FR", "f", "French", ("ff_",)),
    KokoroLanguageSpec("hi", "h", "Hindi", ("hf_", "hm_")),
    KokoroLanguageSpec("it", "i", "Italian", ("if_", "im_")),
    KokoroLanguageSpec("ja", "j", "Japanese", ("jf_", "jm_"), "misaki[ja]"),
    KokoroLanguageSpec("pt-BR", "p", "Brazilian Portuguese", ("pf_", "pm_")),
    KokoroLanguageSpec("zh-CN", "z", "Mandarin Chinese", ("zf_", "zm_"), "misaki[zh]"),
)


_KOKORO_VOICE_IDS: tuple[str, ...] = (
    "af_heart",
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "jf_alpha",
    "jf_gongitsune",
    "jf_nezumi",
    "jf_tebukuro",
    "jm_kumo",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "pf_dora",
    "pm_alex",
    "pm_santa",
)


def _voice_language(voice_id: str) -> KokoroLanguageSpec:
    for spec in KOKORO_LANGUAGES:
        if voice_id.startswith(spec.voice_prefixes):
            return spec
    raise ValueError(f"Unmapped Kokoro voice: {voice_id}")


KOKORO_VOICES: tuple[KokoroVoiceSpec, ...] = tuple(
    KokoroVoiceSpec(
        voice_id=voice_id,
        language_code=_voice_language(voice_id).language_code,
        display_name=voice_id.replace("_", " ").title(),
    )
    for voice_id in _KOKORO_VOICE_IDS
)


class KokoroRuntimeService:
    """Process-local Kokoro pipeline cache with explicit language certification.

    No network/download action is performed by inventory or validation. Creating a
    KPipeline can let the upstream runtime resolve its model assets, so warm-up is
    only reached through explicit warm/generation paths.
    """

    MODEL_ID = "kokoro-82m-v1.0"
    SAMPLE_RATE = 24000

    def __init__(
        self,
        *,
        kokoro_loader: Callable[[], object] | None = None,
        max_cache_entries: int = 3,
    ) -> None:
        self._custom_loader = kokoro_loader is not None
        self._kokoro_loader = kokoro_loader or self._import_kokoro
        self.max_cache_entries = max(1, int(max_cache_entries))
        self._cache: OrderedDict[str, _PipelineSlot] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._load_count = 0
        self._synthesis_count = 0
        self._last_error: str | None = None

    @staticmethod
    def python_api_available() -> bool:
        try:
            return importlib.util.find_spec("kokoro") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def api_available(self) -> bool:
        if not self._custom_loader:
            return self.python_api_available()
        try:
            module = self._kokoro_loader()
        except (ImportError, ModuleNotFoundError):
            return False
        return callable(getattr(module, "KPipeline", None))

    @classmethod
    def supported_languages(cls) -> tuple[KokoroLanguageSpec, ...]:
        return KOKORO_LANGUAGES

    @classmethod
    def language_spec(cls, language_code: str | None) -> KokoroLanguageSpec | None:
        normalized = str(language_code or "").strip().replace("_", "-").casefold()
        aliases = {
            "en": "en-us",
            "en-us": "en-us",
            "en-gb": "en-gb",
            "es-es": "es",
            "es": "es",
            "fr": "fr-fr",
            "fr-fr": "fr-fr",
            "hi-in": "hi",
            "hi": "hi",
            "it-it": "it",
            "it": "it",
            "ja-jp": "ja",
            "ja": "ja",
            "pt": "pt-br",
            "pt-br": "pt-br",
            "zh": "zh-cn",
            "zh-cn": "zh-cn",
        }
        target = aliases.get(normalized, normalized)
        return next(
            (spec for spec in KOKORO_LANGUAGES if spec.language_code.casefold() == target),
            None,
        )

    @classmethod
    def voices_for_language(cls, language_code: str | None) -> tuple[KokoroVoiceSpec, ...]:
        spec = cls.language_spec(language_code)
        if spec is None:
            return ()
        return tuple(voice for voice in KOKORO_VOICES if voice.language_code == spec.language_code)

    @classmethod
    def voice_spec(cls, voice_id: str | None) -> KokoroVoiceSpec | None:
        key = str(voice_id or "").strip().casefold()
        return next((voice for voice in KOKORO_VOICES if voice.voice_id.casefold() == key), None)

    @classmethod
    def certification_issue(
        cls,
        language_code: str | None,
        voice_id: str | None = None,
    ) -> str | None:
        spec = cls.language_spec(language_code)
        if spec is None:
            requested = str(language_code or "unspecified").strip() or "unspecified"
            return (
                f"Kokoro language '{requested}' is not certified by S-Talking. "
                "The official Kokoro v1.0 language set does not include Danish."
            )
        if voice_id:
            voice = cls.voice_spec(voice_id)
            if voice is None:
                return f"Unknown Kokoro voice: {voice_id}"
            if voice.language_code != spec.language_code:
                return (
                    f"Kokoro voice '{voice.voice_id}' is certified for {voice.language_code}, "
                    f"not {spec.language_code}."
                )
        return None

    def warm(self, language_code: str | None) -> KokoroRuntimeHealth:
        spec = self._require_language(language_code)
        self._slot(spec)
        return self.health()

    def synthesize(
        self,
        text: str,
        *,
        language_code: str | None,
        voice_id: str,
        speed: float = 1.0,
        timeout_seconds: float = 90.0,
        cancel_event: threading.Event | None = None,
    ) -> bytes:
        spec = self._require_language(language_code)
        issue = self.certification_issue(spec.language_code, voice_id)
        if issue:
            raise ConfigurationError(issue)
        slot = self._slot(spec)
        cancel_event = cancel_event or threading.Event()
        started = time.monotonic()

        with slot.lock:
            self._check_interrupt(cancel_event, timeout_seconds, started)
            try:
                generator = slot.pipeline(text, voice=voice_id, speed=float(speed or 1.0))
                chunks: list[object] = []
                for _graphemes, _phonemes, audio in generator:
                    self._check_interrupt(cancel_event, timeout_seconds, started)
                    chunks.append(audio)
                payload = self._wav_bytes(chunks)
                self._check_interrupt(cancel_event, timeout_seconds, started)
            except ProviderError:
                raise
            except Exception as exc:
                message = self._safe_error(exc)
                slot.last_error = message
                self._last_error = message
                raise ProviderError(
                    f"Kokoro runtime failed: {message}",
                    provider_code="kokoro_runtime_error",
                    technical_details=message,
                ) from exc

            slot.synthesis_count += 1
            slot.last_error = None
            self._synthesis_count += 1
            self._last_error = None
            return payload

    def restart(self, language_code: str | None = None) -> int:
        with self._cache_lock:
            self._last_error = None
            if language_code is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            spec = self.language_spec(language_code)
            if spec is None:
                return 0
            return 1 if self._cache.pop(spec.pipeline_code, None) is not None else 0

    def health(self) -> KokoroRuntimeHealth:
        with self._cache_lock:
            loaded = tuple(slot.language.language_code for slot in self._cache.values())
            latest_error = next(
                (slot.last_error for slot in reversed(tuple(self._cache.values())) if slot.last_error),
                self._last_error,
            )
            return KokoroRuntimeHealth(
                available=self.api_available(),
                loaded_language_codes=loaded,
                pipeline_count=len(self._cache),
                load_count=self._load_count,
                synthesis_count=self._synthesis_count,
                last_error=latest_error,
            )

    def _slot(self, spec: KokoroLanguageSpec) -> _PipelineSlot:
        with self._cache_lock:
            existing = self._cache.get(spec.pipeline_code)
            if existing is not None:
                self._cache.move_to_end(spec.pipeline_code)
                return existing

            module = self._load_module()
            pipeline_class = getattr(module, "KPipeline", None)
            if not callable(pipeline_class):
                raise ConfigurationError("Installed Kokoro package does not expose KPipeline.")
            try:
                pipeline = pipeline_class(lang_code=spec.pipeline_code)
            except Exception as exc:
                message = self._safe_error(exc)
                self._last_error = message
                extra_hint = f" Install {spec.optional_extra}." if spec.optional_extra else ""
                raise ProviderError(
                    f"Kokoro pipeline could not be loaded for {spec.display_name}.{extra_hint}",
                    provider_code="kokoro_pipeline_load_failed",
                    technical_details=message,
                ) from exc

            slot = _PipelineSlot(spec, pipeline)
            self._cache[spec.pipeline_code] = slot
            self._cache.move_to_end(spec.pipeline_code)
            self._load_count += 1
            self._evict_if_needed(exclude=spec.pipeline_code)
            self._last_error = None
            return slot

    def _load_module(self) -> object:
        try:
            return self._kokoro_loader()
        except (ImportError, ModuleNotFoundError) as exc:
            raise ConfigurationError(
                "Kokoro Python runtime is unavailable. Install the optional kokoro runtime."
            ) from exc

    @classmethod
    def _require_language(cls, language_code: str | None) -> KokoroLanguageSpec:
        spec = cls.language_spec(language_code)
        if spec is None:
            raise ConfigurationError(cls.certification_issue(language_code) or "Unsupported Kokoro language.")
        return spec

    @classmethod
    def _wav_bytes(cls, chunks: list[object]) -> bytes:
        if not chunks:
            raise ProviderError("Kokoro returned no audio.", provider_code="kokoro_empty_audio")
        try:
            pcm = bytearray()
            sample_count = 0
            for chunk in chunks:
                for sample in cls._audio_samples(chunk):
                    if not math.isfinite(sample):
                        raise ValueError("Kokoro returned a non-finite audio sample.")
                    clipped = min(1.0, max(-1.0, sample))
                    pcm.extend(struct.pack("<h", int(clipped * 32767.0)))
                    sample_count += 1
            if sample_count == 0:
                raise ProviderError("Kokoro returned no audio.", provider_code="kokoro_empty_audio")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "Kokoro audio could not be converted to WAV.",
                provider_code="kokoro_audio_encode_failed",
                technical_details=cls._safe_error(exc),
            ) from exc

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(cls.SAMPLE_RATE)
            wav_file.writeframes(bytes(pcm))
        return output.getvalue()

    @classmethod
    def _audio_samples(cls, chunk: object) -> tuple[float, ...]:
        value = chunk
        for method_name in ("detach", "cpu"):
            method = getattr(value, method_name, None)
            if callable(method):
                value = method()

        reshape = getattr(value, "reshape", None)
        if callable(reshape):
            try:
                value = reshape(-1)
            except (TypeError, ValueError):
                pass

        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            value = tolist()

        samples: list[float] = []

        def collect(item: object) -> None:
            if isinstance(item, (int, float)):
                samples.append(float(item))
                return
            if isinstance(item, (str, bytes, bytearray)):
                raise TypeError("Kokoro audio chunk is not numeric.")
            try:
                iterator = iter(item)  # type: ignore[arg-type]
            except TypeError as exc:
                scalar = getattr(item, "item", None)
                if callable(scalar):
                    collect(scalar())
                    return
                raise TypeError("Kokoro audio chunk is not iterable numeric data.") from exc
            for child in iterator:
                collect(child)

        collect(value)
        return tuple(samples)

    @staticmethod
    def _check_interrupt(
        cancel_event: threading.Event,
        timeout_seconds: float,
        started: float,
    ) -> None:
        if cancel_event.is_set():
            raise ProviderError("Generation cancelled by user.", provider_code="cancelled")
        if timeout_seconds > 0 and (time.monotonic() - started) > timeout_seconds:
            raise ProviderError(
                "Kokoro synthesis timed out.",
                retryable=True,
                provider_code="timeout",
            )

    def _evict_if_needed(self, *, exclude: str) -> None:
        while len(self._cache) > self.max_cache_entries:
            key = next(iter(self._cache))
            if key == exclude and len(self._cache) > 1:
                key = list(self._cache.keys())[1]
            self._cache.pop(key, None)

    @staticmethod
    def _import_kokoro() -> object:
        return importlib.import_module("kokoro")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:800]


_SHARED_RUNTIME = KokoroRuntimeService()


def shared_kokoro_runtime_service() -> KokoroRuntimeService:
    return _SHARED_RUNTIME
