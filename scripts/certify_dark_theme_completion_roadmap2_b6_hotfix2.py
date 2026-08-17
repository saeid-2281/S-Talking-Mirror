from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.runtime_font_support import ensure_readable_runtime_font
from app.gui.theme_accessibility_v2 import (
    DARK_THEME_LEGACY_SURFACE_COLORS,
    dark_theme_completion_stylesheet,
    theme_accessibility_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Certify B6 Hotfix 2 dark-theme completion.")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    application = QApplication.instance() or QApplication([])
    font_ok, font_family = ensure_readable_runtime_font(application, require_explicit_font=True)
    context = create_application_context(
        create_service_container(RuntimeConfig.from_root(Path.cwd()))
    )
    window = MainWindow(context)
    window.resize(1800, 1000)
    window.apply_theme("Dark")
    window.show()
    application.processEvents()

    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    completion = dark_theme_completion_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    composite = theme_accessibility_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )

    checks: dict[str, bool] = {
        "runtime_font_available": font_ok and bool(font_family),
        "dark_only_layer_present": "Roadmap 2 B6 Hotfix 2" in completion,
        "completion_is_last_overlay": composite.rfind("Roadmap 2 B6 Hotfix 2")
        > composite.rfind("Roadmap 2 A12.1"),
        "legacy_navy_literals_absent_from_completion": all(
            color.upper() not in completion.upper()
            for color in DARK_THEME_LEGACY_SURFACE_COLORS
        ),
        "left_dock_canvas": window.left_dock.property("a121SurfaceFamily") == "canvas",
        "right_dock_canvas": window.right_dock.property("a121SurfaceFamily") == "canvas",
        "left_tabs_canvas": window.left_tabs.property("a121SurfaceFamily") == "canvas",
        "right_tabs_canvas": window.right_tabs.property("a121SurfaceFamily") == "canvas",
        "monitor_scroll_canvas": window.monitor_scroll.property("a121SurfaceFamily") == "canvas",
        "queue_surface": window.queue_workspace.property("a121SurfaceFamily") == "surface",
        "selected_row_surface": window.selected_row_panel.property("a121SurfaceFamily") == "surface",
        "left_dock_palette": window.left_dock.palette()
        .color(QPalette.ColorRole.Window)
        .name()
        .lower()
        == semantic.canvas.lower(),
        "right_dock_palette": window.right_dock.palette()
        .color(QPalette.ColorRole.Window)
        .name()
        .lower()
        == semantic.canvas.lower(),
        "neutral_selection_surface": f"selection-background-color:{semantic.surface_secondary}"
        in completion,
        "connection_surface": "QPushButton#connectionStatus" in completion
        and f"background:{semantic.surface_secondary}" in completion,
    }

    screenshot = output / "dark-theme-completion.png"
    screenshot_ok = window.grab().save(str(screenshot), "PNG")
    checks["runtime_screenshot_written"] = bool(screenshot_ok and screenshot.exists())

    failed = [name for name, passed in checks.items() if not passed]
    payload = {
        "schema_version": 1,
        "phase": "Roadmap 2 B6 Hotfix 2",
        "status": "CERTIFIED" if not failed else "FAILED",
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "soft_professional": {
            "canvas": semantic.canvas,
            "surface": semantic.surface,
            "surface_secondary": semantic.surface_secondary,
            "primary": semantic.primary,
        },
        "screenshot": str(screenshot),
        "scope": "presentation-only dark surface completion",
    }
    (output / "certification.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    window.close()
    application.processEvents()

    print(f"Roadmap 2 B6 Hotfix 2 dark-theme certification: {payload['status']}")
    print(f"Checks: {len(checks) - len(failed)}/{len(checks)}")
    print(f"Evidence: {output}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
