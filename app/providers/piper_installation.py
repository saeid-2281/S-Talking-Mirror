from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config.runtime import RuntimeConfig


PIPER_EXECUTABLE_ENV = "S_TALKING_PIPER_EXECUTABLE"


@dataclass(frozen=True)
class PiperCliInvocation:
    """A runnable Piper CLI prefix.

    The managed Portable installation may lose the pip-generated ``piper.exe``
    console-script wrapper while its Python environment/package remains intact.
    In that case S-Talking can safely invoke the same CLI as
    ``python.exe -m piper`` without changing provider/model/language authority.
    """

    executable: str
    prefix_args: tuple[str, ...] = ()
    launch_mode: str = "console-script"

    def command(self, *args: str) -> list[str]:
        return [self.executable, *self.prefix_args, *args]


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


def managed_piper_python_candidates(runtime: RuntimeConfig) -> tuple[Path, ...]:
    root = managed_piper_root(runtime)
    return (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "Scripts" / "python.exe",
        root / "bin" / "python",
    )


def managed_piper_module_candidates(runtime: RuntimeConfig) -> tuple[Path, ...]:
    root = managed_piper_root(runtime)
    candidates: list[Path] = [
        root / ".venv" / "Lib" / "site-packages" / "piper" / "__main__.py",
        root / "Lib" / "site-packages" / "piper" / "__main__.py",
    ]
    for lib_root in (root / ".venv" / "lib", root / "lib"):
        if not lib_root.is_dir():
            continue
        try:
            versions = sorted(lib_root.glob("python*/site-packages/piper/__main__.py"))
        except OSError:
            versions = []
        candidates.extend(versions)
    return tuple(candidates)


def _managed_python_module_invocation(runtime: RuntimeConfig) -> PiperCliInvocation | None:
    if not any(candidate.is_file() for candidate in managed_piper_module_candidates(runtime)):
        return None
    for candidate in managed_piper_python_candidates(runtime):
        if candidate.is_file():
            return PiperCliInvocation(
                executable=str(candidate.resolve()),
                prefix_args=("-m", "piper"),
                launch_mode="python-module",
            )
    return None


def resolve_piper_cli(
    runtime: RuntimeConfig | None = None,
    *,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> PiperCliInvocation | None:
    """Resolve a runnable Piper CLI without requiring PATH mutation.

    Resolution order:
    1. explicit S_TALKING_PIPER_EXECUTABLE override,
    2. managed pip console-script wrapper,
    3. managed venv Python + ``-m piper`` fallback,
    4. legacy PATH lookup.

    The Python-module fallback makes the Portable runtime resilient when the
    pip-generated ``piper.exe`` wrapper is removed after migration while the
    Piper package/environment remains intact.
    """

    explicit = str(os.environ.get(PIPER_EXECUTABLE_ENV) or "").strip()
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_file():
            return PiperCliInvocation(str(explicit_path.resolve()))

    active_runtime = runtime or runtime_for_current_process()
    for candidate in managed_piper_executable_candidates(active_runtime):
        if candidate.is_file():
            return PiperCliInvocation(str(candidate.resolve()))

    module_invocation = _managed_python_module_invocation(active_runtime)
    if module_invocation is not None:
        return module_invocation

    try:
        resolved = executable_finder("piper")
    except OSError:
        resolved = None
    if resolved:
        return PiperCliInvocation(str(resolved))
    return None


def resolve_piper_executable(
    runtime: RuntimeConfig | None = None,
    *,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Return the executable component of the resolved Piper CLI invocation."""

    invocation = resolve_piper_cli(runtime, executable_finder=executable_finder)
    return invocation.executable if invocation is not None else None
