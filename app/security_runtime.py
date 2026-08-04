from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from app.config.runtime import RuntimeConfig


_DLL_DIRECTORY_COOKIES: list[object] = []


def harden_windows_dll_search(runtime: RuntimeConfig) -> tuple[str, str]:
    """Remove the current directory from implicit DLL search before Qt loads."""
    if sys.platform != "win32":
        return "not_applicable", "DLL search hardening applies to Windows frozen builds."
    if not getattr(sys, "frozen", False):
        return "not_measured", "Source-mode development does not modify process DLL search policy."
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        load_library_search_default_dirs = 0x00001000
        if not kernel32.SetDefaultDllDirectories(load_library_search_default_dirs):
            raise ctypes.WinError(ctypes.get_last_error())
        add_directory = getattr(os, "add_dll_directory", None)
        trusted: tuple[Path, ...] = (runtime.app_root, runtime.app_root / "_internal")
        if callable(add_directory):
            for directory in trusted:
                if directory.is_dir():
                    _DLL_DIRECTORY_COOKIES.append(add_directory(str(directory)))
        os.environ["S_TALKING_DLL_SEARCH_HARDENED"] = "1"
        return (
            "pass",
            "Default DLL search directories are restricted to trusted application and system paths.",
        )
    except Exception as exc:
        return "block", f"Could not enforce hardened DLL search policy: {exc}"
