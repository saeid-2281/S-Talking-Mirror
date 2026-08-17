from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


WINDOWS_FONT_CANDIDATES = (
    "segoeui.ttf",
    "segoeuib.ttf",
    "tahoma.ttf",
    "arial.ttf",
)


def ensure_readable_runtime_font(
    application: QApplication,
    *,
    require_explicit_font: bool = False,
) -> tuple[bool, str]:
    """Ensure Qt has a readable UI font without bundling private font files.

    The normal Windows platform plugin exposes system fonts automatically.
    Offscreen/headless Qt can start with an empty font database, which previously
    produced square-glyph screenshots that still passed visual certification.
    When needed, this function registers a Windows system font from
    ``%WINDIR%\\Fonts`` and applies it to the application.

    Returns ``(usable, family)``.  ``require_explicit_font`` is intended for
    screenshot certifiers: on Windows it requires a concrete family to be
    available instead of silently accepting Qt's square-glyph fallback.
    """

    families = tuple(QFontDatabase.families())
    preferred = next(
        (
            family
            for family in ("Segoe UI", "Segoe UI Variable", "Tahoma", "Arial")
            if family in families
        ),
        "",
    )

    if not preferred and sys.platform == "win32":
        windows_root = Path(os.environ.get("WINDIR") or r"C:\Windows")
        fonts_root = windows_root / "Fonts"
        for filename in WINDOWS_FONT_CANDIDATES:
            candidate = fonts_root / filename
            if not candidate.is_file():
                continue
            font_id = QFontDatabase.addApplicationFont(str(candidate))
            if font_id < 0:
                continue
            registered = QFontDatabase.applicationFontFamilies(font_id)
            if registered:
                preferred = registered[0]
                break

    if preferred:
        # Keep Qt's current typography metrics intact whenever the selected
        # family is already usable.  Reconstructing QFont from a rounded point
        # size changes global text metrics (for example 9.5 -> 10pt) and can
        # make unrelated dock/layout tests order-dependent after a screenshot
        # certifier runs in the shared QApplication.
        current = QFont(application.font())
        if current.family().strip().casefold() == preferred.casefold():
            return True, preferred

        replacement = QFont(current)
        replacement.setFamily(preferred)
        application.setFont(replacement)
        return True, preferred

    current_family = application.font().family().strip()
    usable = bool(current_family) and not (
        require_explicit_font and sys.platform == "win32"
    )
    return usable, current_family
