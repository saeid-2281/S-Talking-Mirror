from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime paths for the application."""

    app_root: Path
    data_dir: Path
    database_path: Path
    legacy_database_path: Path
    settings_path: Path
    log_dir: Path
    cache_dir: Path
    default_output_dir: Path
    reports_dir: Path
    artifacts_dir: Path
    resource_dir: Path | None = None

    @classmethod
    def from_root(cls, app_root: Path | None = None) -> "RuntimeConfig":
        if getattr(sys, "frozen", False):
            return cls.from_frozen()
        root = (app_root or Path.cwd()).resolve()
        data_dir = root / "data"
        return cls(
            app_root=root,
            data_dir=data_dir,
            database_path=data_dir / "s_talking.db",
            legacy_database_path=data_dir / "s-talking.db",
            settings_path=root / "settings.json",
            log_dir=root / "logs",
            cache_dir=root / "cache",
            default_output_dir=root / "output",
            reports_dir=root / "reports",
            artifacts_dir=root / "artifacts",
            resource_dir=root,
        )

    @classmethod
    def from_frozen(cls) -> "RuntimeConfig":
        executable = Path(sys.executable).resolve()
        exe_dir = executable.parent
        bundle_root = Path(getattr(sys, "_MEIPASS", exe_dir)).resolve()
        portable_marker = exe_dir / "portable.mode"
        if portable_marker.exists():
            writable_root = exe_dir / "S-Talking-Data"
        else:
            local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            writable_root = local_app_data / "S-Talking"
        data_dir = writable_root / "data"
        settings_dir = writable_root / "settings"
        diagnostics_dir = writable_root / "diagnostics"
        return cls(
            app_root=exe_dir,
            data_dir=data_dir,
            database_path=data_dir / "s_talking.db",
            legacy_database_path=data_dir / "s-talking.db",
            settings_path=settings_dir / "settings.json",
            log_dir=writable_root / "logs",
            cache_dir=writable_root / "cache",
            default_output_dir=writable_root / "output",
            reports_dir=writable_root / "reports",
            artifacts_dir=diagnostics_dir,
            resource_dir=bundle_root,
        )

    def ensure_directories(self) -> None:
        for path in [
            self.data_dir,
            self.log_dir,
            self.cache_dir,
            self.default_output_dir,
            self.reports_dir,
            self.artifacts_dir,
            self.settings_path.parent,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def bundled_root(self) -> Path:
        return self.resource_dir or self.app_root

    def resource_path(self, *parts: str) -> Path:
        return self.bundled_root.joinpath(*parts)
