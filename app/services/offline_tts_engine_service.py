from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config.runtime import RuntimeConfig
from app.models import AppSettings
from app.models.offline_tts_engine import (
    OfflineEngineInventory,
    OfflineEngineSnapshot,
    OfflineVoiceDescriptor,
)
from app.models.piper_runtime import PiperRuntimeHealth
from app.providers.kokoro_runtime import KokoroRuntimeHealth, KokoroRuntimeService, shared_kokoro_runtime_service
from app.providers.piper_runtime import (
    PiperRuntimeService,
    shared_piper_runtime_service,
)
from app.services.piper_model_manager import PiperManagedVoice, PiperModelManager


@dataclass(frozen=True)
class OfflineEngineSpec:
    engine_id: str
    display_name: str
    provider_id: str
    dependency_name: str
    executable_names: tuple[str, ...] = ()
    asset_kind: str = "runtime-managed"
    accelerators: tuple[str, ...] = ("CPU",)


class OfflineTTSEngineService:
    """Inventory and explicit lifecycle authority for local TTS runtimes.

    Inventory and voice discovery remain read-only. Phase 102 adds explicit local
    model/runtime management actions, but inventory still never installs packages,
    downloads voices, synthesizes audio, or mutates provider settings.
    """

    SPECS = (
        OfflineEngineSpec(
            engine_id="piper",
            display_name="Piper",
            provider_id="piper",
            dependency_name="piper",
            executable_names=("piper",),
            asset_kind="onnx",
            accelerators=("CPU", "CUDA optional"),
        ),
        OfflineEngineSpec(
            engine_id="kokoro",
            display_name="Kokoro Local",
            provider_id="kokoro",
            dependency_name="kokoro",
            asset_kind="runtime-catalog",
            accelerators=("PyTorch runtime",),
        ),
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        module_finder: Callable[[str], object | None] | None = None,
        executable_finder: Callable[[str], str | None] | None = None,
        piper_runtime: PiperRuntimeService | None = None,
        kokoro_runtime: KokoroRuntimeService | None = None,
        piper_model_manager: PiperModelManager | None = None,
    ) -> None:
        self.runtime = runtime
        self._module_finder = module_finder or importlib.util.find_spec
        self._executable_finder = executable_finder or shutil.which
        self.piper_runtime = piper_runtime or shared_piper_runtime_service()
        self.kokoro_runtime = kokoro_runtime or shared_kokoro_runtime_service()
        self.piper_model_manager = piper_model_manager or PiperModelManager(runtime)

    def inventory(self, settings: AppSettings | None = None) -> OfflineEngineInventory:
        active = settings or AppSettings()
        return OfflineEngineInventory(
            tuple(self.snapshot(spec.engine_id, active) for spec in self.SPECS)
        )

    def snapshot(
        self,
        engine_id: str,
        settings: AppSettings | None = None,
    ) -> OfflineEngineSnapshot:
        spec = self._spec(engine_id)
        active = settings or AppSettings()
        module_available = self._module_available(spec.dependency_name)
        executable_path = self._first_executable(spec.executable_names)
        installed = module_available or bool(executable_path)

        if spec.engine_id == "piper":
            return self._piper_snapshot(
                spec,
                active,
                module_available=module_available,
                executable_path=executable_path,
                installed=installed,
            )
        return self._runtime_managed_snapshot(
            spec,
            active,
            module_available=module_available,
            executable_path=executable_path,
            installed=installed,
        )

    def discover_voices(
        self,
        engine_id: str,
        settings: AppSettings | None = None,
    ) -> tuple[OfflineVoiceDescriptor, ...]:
        spec = self._spec(engine_id)
        active = settings or AppSettings()
        if spec.engine_id == "kokoro":
            selected_voice = active.voice_id.strip() if active.provider == "kokoro" else ""
            return tuple(
                OfflineVoiceDescriptor(
                    engine_id="kokoro",
                    voice_id=voice.voice_id,
                    display_name=voice.display_name,
                    model_path=f"runtime://kokoro/{voice.voice_id}",
                    language_code=voice.language_code,
                    sample_rate=self.kokoro_runtime.SAMPLE_RATE,
                    size_bytes=0,
                    config_present=True,
                    selected=voice.voice_id == selected_voice,
                )
                for voice in self.kokoro_runtime.voices_for_language(active.language_code)
            )
        if spec.asset_kind != "onnx":
            return ()
        selected = self._selected_model(active, spec.engine_id)
        candidates: dict[str, Path] = {}

        if selected is not None:
            candidates[self._path_key(selected)] = selected

        for root in self._voice_roots(spec.engine_id, selected):
            if not root.is_dir():
                continue
            try:
                models = sorted(root.rglob("*.onnx"))
            except OSError:
                continue
            for model in models[:200]:
                candidates.setdefault(self._path_key(model), model)

        return tuple(
            self._voice_descriptor(spec.engine_id, model, selected)
            for model in sorted(candidates.values(), key=lambda item: item.name.casefold())
            if model.is_file()
        )

    def _piper_snapshot(
        self,
        spec: OfflineEngineSpec,
        settings: AppSettings,
        *,
        module_available: bool,
        executable_path: str | None,
        installed: bool,
    ) -> OfflineEngineSnapshot:
        voices = self.discover_voices(spec.engine_id, settings)
        selected = self._selected_model(settings, spec.engine_id)
        selected_voice = next((voice for voice in voices if voice.selected), None)
        model_ok = bool(selected and selected.is_file())
        config_ok = bool(selected_voice and selected_voice.config_present)
        configured = model_ok and config_ok
        ready = installed and configured
        issues: list[str] = []

        if not installed:
            issues.append("Piper runtime is not installed or discoverable.")
        if selected is None:
            issues.append("No Piper ONNX voice is selected.")
        elif not model_ok:
            issues.append("The selected Piper ONNX model does not exist.")
        elif not config_ok:
            issues.append("The selected Piper voice is missing its .onnx.json config file.")

        if ready:
            state = "Ready for Phase 97 runtime"
            summary = "Piper runtime and selected voice assets are discoverable."
        elif installed:
            state = "Setup required"
            summary = "Piper runtime is present, but voice configuration is incomplete."
        else:
            state = "Runtime missing"
            summary = "Install the optional Piper runtime before local synthesis can be enabled."

        runtime_mode = "python-api" if module_available else "legacy-cli" if executable_path else "unavailable"
        runtime_health = self.piper_runtime.health(selected)
        if ready and runtime_mode == "python-api" and runtime_health.loaded:
            state = "Runtime warm"
            summary = (
                "Piper model is loaded and ready for in-process synthesis on "
                f"{runtime_health.resolved_acceleration.upper()}."
            )
        return OfflineEngineSnapshot(
            engine_id=spec.engine_id,
            display_name=spec.display_name,
            provider_id=spec.provider_id,
            dependency_name=spec.dependency_name,
            installed=installed,
            module_available=module_available,
            executable_path=executable_path,
            runtime_mode=runtime_mode,
            configured=configured,
            ready=ready,
            selected_voice_id=selected_voice.voice_id if selected_voice else None,
            voices=voices,
            accelerators=spec.accelerators,
            state=state,
            summary=summary,
            issues=tuple(issues),
            runtime_loaded=runtime_health.loaded,
            resolved_accelerator=runtime_health.resolved_acceleration,
            runtime_cache_entries=runtime_health.cache_entries,
            runtime_load_count=runtime_health.load_count,
            runtime_synthesis_count=runtime_health.synthesis_count,
            runtime_last_error=runtime_health.last_error,
            runtime_fallback_reason=runtime_health.fallback_reason,
        )


    def inspect_piper_voice(self, model_path: str | Path) -> PiperManagedVoice:
        return self.piper_model_manager.inspect(model_path)

    def import_piper_voice(self, model_path: str | Path) -> PiperManagedVoice:
        """Explicitly copy a validated local Piper voice into the managed model root."""

        return self.piper_model_manager.import_voice(model_path)

    def piper_runtime_health(self, settings: AppSettings | None = None) -> PiperRuntimeHealth:
        active = settings or AppSettings(provider="piper")
        selected = self._selected_model(active, "piper")
        return self.piper_runtime.health(selected)

    def warm_piper(self, settings: AppSettings) -> PiperRuntimeHealth:
        selected = self._selected_model(settings, "piper")
        if selected is None:
            raise ValueError("No Piper ONNX voice is selected.")
        return self.piper_runtime.warm(selected, requested_acceleration="auto")

    def restart_piper(self, settings: AppSettings | None = None) -> int:
        active = settings or AppSettings(provider="piper")
        selected = self._selected_model(active, "piper")
        return self.piper_runtime.restart(selected)


    def kokoro_runtime_health(self) -> KokoroRuntimeHealth:
        return self.kokoro_runtime.health()

    def warm_kokoro(self, settings: AppSettings) -> KokoroRuntimeHealth:
        issue = self.kokoro_runtime.certification_issue(settings.language_code)
        if issue:
            raise ValueError(issue)
        return self.kokoro_runtime.warm(settings.language_code)

    def restart_kokoro(self, settings: AppSettings | None = None) -> int:
        active = settings or AppSettings(provider="kokoro")
        return self.kokoro_runtime.restart(active.language_code)

    def _runtime_managed_snapshot(
        self,
        spec: OfflineEngineSpec,
        settings: AppSettings,
        *,
        module_available: bool,
        executable_path: str | None,
        installed: bool,
    ) -> OfflineEngineSnapshot:
        if spec.engine_id != "kokoro":
            selected_voice = settings.voice_id.strip() if settings.provider == spec.provider_id else ""
            configured = installed
            ready = installed
            issues = () if installed else (f"Optional dependency is missing: {spec.dependency_name}",)
            return OfflineEngineSnapshot(
                engine_id=spec.engine_id,
                display_name=spec.display_name,
                provider_id=spec.provider_id,
                dependency_name=spec.dependency_name,
                installed=installed,
                module_available=module_available,
                executable_path=executable_path,
                runtime_mode="python-api" if module_available else "unavailable",
                configured=configured,
                ready=ready,
                selected_voice_id=selected_voice or None,
                voices=(),
                accelerators=spec.accelerators,
                state="Runtime available" if installed else "Runtime missing",
                summary=(
                    "Runtime-managed local engine is available."
                    if installed
                    else "Install the optional local runtime to enable this provider."
                ),
                issues=issues,
            )

        selected_voice = settings.voice_id.strip() if settings.provider == "kokoro" else ""
        certification_issue = self.kokoro_runtime.certification_issue(
            settings.language_code,
            selected_voice or None,
        )
        voices = self.discover_voices("kokoro", settings)
        configured = installed and certification_issue is None and bool(selected_voice)
        ready = configured
        health = self.kokoro_runtime.health()
        language = self.kokoro_runtime.language_spec(settings.language_code)
        issues: list[str] = []
        if not installed:
            issues.append("Optional dependency is missing: kokoro")
        if certification_issue:
            issues.append(certification_issue)
        elif not selected_voice:
            issues.append("Select a certified Kokoro voice for the configured language.")

        if ready:
            state = "Ready"
            summary = "Kokoro v1.0 runtime, language, and voice are certified for local synthesis."
        elif installed and certification_issue:
            state = "Language not certified"
            summary = "Kokoro is installed, but the configured language is outside the certified v1.0 set."
        elif installed:
            state = "Voice required"
            summary = "Kokoro is installed and language-certified; select a compatible voice."
        else:
            state = "Runtime missing"
            summary = "Install the optional Kokoro runtime before local synthesis can be enabled."

        return OfflineEngineSnapshot(
            engine_id=spec.engine_id,
            display_name=spec.display_name,
            provider_id=spec.provider_id,
            dependency_name=spec.dependency_name,
            installed=installed,
            module_available=module_available,
            executable_path=executable_path,
            runtime_mode="python-api" if module_available else "unavailable",
            configured=configured,
            ready=ready,
            selected_voice_id=selected_voice or None,
            voices=voices,
            accelerators=spec.accelerators,
            state=state,
            summary=summary,
            issues=tuple(issues),
            runtime_loaded=bool(language and language.language_code in health.loaded_language_codes),
            resolved_accelerator="runtime" if health.pipeline_count else None,
            runtime_cache_entries=health.pipeline_count,
            runtime_load_count=health.load_count,
            runtime_synthesis_count=health.synthesis_count,
            runtime_last_error=health.last_error,
        )

    def _voice_roots(self, engine_id: str, selected: Path | None) -> tuple[Path, ...]:
        roots: list[Path] = []
        if selected is not None:
            roots.append(selected.parent)
        roots.extend(
            [
                self.runtime.data_dir / "offline-voices" / engine_id,
                self.runtime.app_root / "models" / engine_id,
                self.runtime.settings_path.parent / "offline-voices" / engine_id,
            ]
        )
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = self._path_key(root)
            if key in seen:
                continue
            seen.add(key)
            unique.append(root)
        return tuple(unique)

    def _voice_descriptor(
        self,
        engine_id: str,
        model: Path,
        selected: Path | None,
    ) -> OfflineVoiceDescriptor:
        config = Path(f"{model}.json")
        metadata = self._read_voice_config(config)
        language = metadata.get("language") if isinstance(metadata.get("language"), dict) else {}
        audio = metadata.get("audio") if isinstance(metadata.get("audio"), dict) else {}
        language_code = self._string(language.get("code")) or self._string(metadata.get("language_code"))
        sample_rate = self._integer(audio.get("sample_rate")) or self._integer(metadata.get("sample_rate"))
        speaker_count = self._integer(metadata.get("num_speakers"))
        display_name = self._string(metadata.get("dataset")) or model.stem
        return OfflineVoiceDescriptor(
            engine_id=engine_id,
            voice_id=model.stem,
            display_name=display_name,
            model_path=str(model.resolve()),
            config_path=str(config.resolve()) if config.is_file() else None,
            language_code=language_code,
            sample_rate=sample_rate,
            speaker_count=speaker_count,
            size_bytes=self._safe_size(model),
            config_present=config.is_file(),
            selected=bool(selected and self._path_key(selected) == self._path_key(model)),
        )

    @staticmethod
    def _read_voice_config(path: Path) -> dict[str, object]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return max(0, int(path.stat().st_size))
        except OSError:
            return 0

    @staticmethod
    def _selected_model(settings: AppSettings, engine_id: str) -> Path | None:
        if engine_id != "piper" or not settings.piper_model_path:
            return None
        return Path(settings.piper_model_path).expanduser()

    def _module_available(self, dependency: str) -> bool:
        try:
            return self._module_finder(dependency) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def _first_executable(self, names: tuple[str, ...]) -> str | None:
        for name in names:
            try:
                resolved = self._executable_finder(name)
            except OSError:
                resolved = None
            if resolved:
                return str(resolved)
        return None

    @classmethod
    def _spec(cls, engine_id: str) -> OfflineEngineSpec:
        key = str(engine_id or "").strip().casefold()
        for spec in cls.SPECS:
            if spec.engine_id.casefold() == key:
                return spec
        raise KeyError(f"Unknown offline TTS engine: {engine_id}")

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except OSError:
            return str(path.absolute()).casefold()

    @staticmethod
    def _string(value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _integer(value: object) -> int | None:
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result >= 0 else None
