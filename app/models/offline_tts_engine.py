from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OfflineVoiceDescriptor:
    engine_id: str
    voice_id: str
    display_name: str
    model_path: str
    config_path: str | None = None
    language_code: str | None = None
    sample_rate: int | None = None
    speaker_count: int | None = None
    size_bytes: int = 0
    config_present: bool = False
    selected: bool = False


@dataclass(frozen=True)
class OfflineEngineSnapshot:
    engine_id: str
    display_name: str
    provider_id: str
    dependency_name: str
    installed: bool
    module_available: bool
    executable_path: str | None
    runtime_mode: str
    configured: bool
    ready: bool
    selected_voice_id: str | None
    voices: tuple[OfflineVoiceDescriptor, ...]
    accelerators: tuple[str, ...]
    state: str
    summary: str
    issues: tuple[str, ...] = ()
    runtime_loaded: bool = False
    resolved_accelerator: str | None = None
    runtime_cache_entries: int = 0
    runtime_load_count: int = 0
    runtime_synthesis_count: int = 0
    runtime_last_error: str | None = None
    runtime_fallback_reason: str | None = None


@dataclass(frozen=True)
class OfflineEngineInventory:
    engines: tuple[OfflineEngineSnapshot, ...]

    @property
    def ready_count(self) -> int:
        return sum(1 for engine in self.engines if engine.ready)

    @property
    def installed_count(self) -> int:
        return sum(1 for engine in self.engines if engine.installed)

    def engine(self, engine_id: str) -> OfflineEngineSnapshot | None:
        key = str(engine_id or "").strip().casefold()
        return next((engine for engine in self.engines if engine.engine_id.casefold() == key), None)
