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
    """Read-only inventory and health authority for local TTS runtimes.

    Phase 96 deliberately does not install packages, download voices, start local
    servers, synthesize audio, or mutate provider settings. It only describes the
    local engines that S-Talking already knows how to route to.
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
            asset_kind="runtime-managed",
            accelerators=("Runtime managed",),
        ),
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        module_finder: Callable[[str], object | None] | None = None,
        executable_finder: Callable[[str], str | None] | None = None,
    ) -> None:
        self.runtime = runtime
        self._module_finder = module_finder or importlib.util.find_spec
        self._executable_finder = executable_finder or shutil.which

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
        if spec.asset_kind != "onnx":
            return ()
        active = settings or AppSettings()
        selected = self._selected_model(active, spec.engine_id)
        candidates: dict[str, Path] = {}

        if selected is not None:
            candidates[self._path_key(selected)] = selected

        for root in self._voice_roots(spec.engine_id, selected):
            if not root.is_dir():
                continue
            try:
                models = sorted(root.glob("*.onnx"))
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
        )

    def _runtime_managed_snapshot(
        self,
        spec: OfflineEngineSpec,
        settings: AppSettings,
        *,
        module_available: bool,
        executable_path: str | None,
        installed: bool,
    ) -> OfflineEngineSnapshot:
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
