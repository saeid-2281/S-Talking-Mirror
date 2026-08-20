from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from app.config.runtime import RuntimeConfig


PIPER_EXECUTABLE_ENV = "S_TALKING_PIPER_EXECUTABLE"


def runtime_for_current_process() -> RuntimeConfig:
    return RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()


def managed_piper_root(runtime: RuntimeConfig) -> Path:
    """Return the writable Piper engine root used by Portable state migration."""

    return runtime.data_dir.parent / "local-engines" / "piper"


def managed_piper_executable_candidates(runtime: RuntimeConfig) -> tuple[Path, ...]:
    root = managed_piper_root(runtime)
    return (
        root / ".venv" / "Scripts" / "piper.exe",
        root / ".venv" / "bin" / "piper",
        root / "Scripts" / "piper.exe",
        root / "bin" / "piper",
        root / "piper.exe",
        root / "piper",
    )


def resolve_piper_executable(
    runtime: RuntimeConfig | None = None,
    *,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Resolve Piper without requiring a launcher to mutate process PATH.

    An explicit environment override wins only when it points to an existing file.
    The managed Portable runtime is checked next, then the normal PATH lookup is
    retained as the legacy/source-mode fallback.
    """

    explicit = str(os.environ.get(PIPER_EXECUTABLE_ENV) or "").strip()
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_file():
            return str(explicit_path.resolve())

    active_runtime = runtime or runtime_for_current_process()
    for candidate in managed_piper_executable_candidates(active_runtime):
        if candidate.is_file():
            return str(candidate.resolve())

    try:
        resolved = executable_finder("piper")
    except OSError:
        resolved = None
    return str(resolved) if resolved else None
