from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.about_dialog import AboutDialog
from app.gui.icons import ICON_REGISTRY, icon, required_icon_names
from app.gui.theme import BRAND_BLUE, DARK_TOKENS, LIGHT_TOKENS, VOICE_TEAL, WARM_ACCENT


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_brand_assets_are_present() -> None:
    brand = Path("app/resources/brand")
    required = {
        "logo-symbol.svg",
        "logo-horizontal-dark.svg",
        "logo-horizontal-light.svg",
        "app-icon.svg",
        "favicon.svg",
        "wordmark.svg",
        "monochrome.svg",
        "app-icon.ico",
        "README.md",
    }
    required.update({f"app-icon-{size}.png" for size in (16, 24, 32, 48, 64, 128, 256, 512)})

    missing = [name for name in sorted(required) if not (brand / name).exists()]

    assert not missing
    assert (brand / "app-icon.ico").stat().st_size > 0


def test_official_logo_master_hash_and_derivatives_are_present() -> None:
    official = Path("app/resources/brand/official")
    manifest = json.loads((official / "brand-manifest.json").read_text(encoding="utf-8"))
    master = official / manifest["master"]
    expected_hash = "ee062816f60038130f7be4fafe58fc0a7378fdc32f967e2b4faf479d40e9e0e9"

    assert manifest["sha256"] == expected_hash
    assert hashlib.sha256(master.read_bytes()).hexdigest() == expected_hash
    assert (official / manifest["derived_ico"]).stat().st_size > 0
    assert all((official / name).exists() and (official / name).stat().st_size > 0 for name in manifest["derived_png"])


def test_theme_token_completeness_and_brand_palette() -> None:
    required = {
        "canvas",
        "surface",
        "surface_raised",
        "surface_soft",
        "input",
        "overlay",
        "border_subtle",
        "border",
        "border_strong",
        "focus",
        "text_primary",
        "text_secondary",
        "text_muted",
        "text_disabled",
        "text_inverse",
        "primary",
        "primary_hover",
        "primary_pressed",
        "secondary_hover",
        "destructive",
        "success",
        "info",
        "warning",
        "error",
        "pending",
        "running",
        "skipped",
        "favorite",
        "selected_row",
    }

    assert set(BRAND_BLUE) == {str(value) for value in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900)}
    assert VOICE_TEAL["500"] == "#14B8A6"
    assert WARM_ACCENT["500"] == "#F59E0B"
    assert required.issubset(DARK_TOKENS)
    assert required.issubset(LIGHT_TOKENS)
    assert DARK_TOKENS["canvas"] == "#0A0F1C"
    assert LIGHT_TOKENS["canvas"] == "#F3F6FA"


def test_icon_registry_completeness_and_qicon_creation() -> None:
    _app()
    required = {
        "add",
        "remove",
        "edit",
        "delete",
        "copy",
        "open",
        "folder",
        "save",
        "refresh",
        "search",
        "filter",
        "sort",
        "play",
        "pause",
        "stop",
        "retry",
        "skip",
        "reset",
        "favorite-outline",
        "favorite-filled",
        "voice",
        "waveform",
        "provider/account",
        "model",
        "language",
        "dictionary",
        "settings",
        "project",
        "queue",
        "report",
        "notification",
        "activity",
        "history",
        "health",
        "warning",
        "error",
        "success",
        "info",
        "more",
        "chevron-up",
        "chevron-down",
        "chevron-left",
        "chevron-right",
    }

    assert required.issubset(required_icon_names())
    assert set(ICON_REGISTRY) == required_icon_names()
    assert not icon("play").isNull()


def test_about_dialog_identity_and_runtime_copy(tmp_path: Path) -> None:
    app = _app()
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    dialog = AboutDialog(runtime)
    dialog.show()
    app.processEvents()

    assert dialog.windowTitle() == "About S Talking"
    assert "S Talking" in dialog.runtime_info.toPlainText()
    dialog.copy_runtime_information()
    assert "Reports directory" in app.clipboard().text()
    assert dialog.minimumWidth() >= 520
    assert dialog.windowFlags() & Qt.Dialog
    dialog.close()


def test_pyinstaller_uses_brand_icon() -> None:
    spec = Path("packaging/S-Talking.spec").read_text(encoding="utf-8")
    assert '"official" / "S-Logo.ico"' in spec
    assert "s-talking.ico" not in spec


def test_design_docs_exist() -> None:
    for path in [Path("docs/BRAND_SYSTEM.md"), Path("docs/DESIGN_SYSTEM.md"), Path("docs/UI_COMPONENTS.md")]:
        assert path.exists()
        assert "S Talking" in path.read_text(encoding="utf-8")
