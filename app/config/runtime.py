from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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

    @classmethod
    def from_root(cls, app_root: Path | None = None) -> "RuntimeConfig":
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
        )

    def ensure_directories(self) -> None:
        for path in [
            self.data_dir,
            self.log_dir,
            self.cache_dir,
            self.default_output_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)
