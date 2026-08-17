from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.runtime_font_support import ensure_readable_runtime_font
from app.gui.theme_accessibility_v2 import (
    THEME_SURFACE_COHERENCE_THEMES,
    theme_surface_coherence_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


CERTIFICATION_VERSION = "roadmap2-a12.1-v1"
EXPECTED_BASELINE_COMMIT = "babacdadda12663ac5d3d5bbcfe8514fcb65a8ee"
EXPECTED_THEMES = ("System", "Light", "Dark")
EXPECTED_THEME_SET = frozenset(EXPECTED_THEMES)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _events(application: QApplication, count: int = 4) -> None:
    for _ in range(count):
        application.processEvents()


def _capture(widget: QWidget, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"Unable to capture {path.name}")
    return {
        "file": path.name,
        "width": pixmap.width(),
        "height": pixmap.height(),
        "sha256": _sha256(path),
    }


def certify_window(window: MainWindow, output: Path) -> dict[str, Any]:
    application = QApplication.instance()
    if application is None:
        raise RuntimeError("QApplication required")

    output.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    available_themes = tuple(window.theme_manager.available_themes())
    available_theme_set = frozenset(available_themes)
    public_theme_set = frozenset(window.theme_actions)
    checks.append(
        {
            "name": "exact_public_three_theme_contract",
            "passed": public_theme_set == EXPECTED_THEME_SET,
            "detail": ",".join(window.theme_actions),
        }
    )
    checks.append(
        {
            "name": "theme_manager_supports_public_theme_contract",
            "passed": EXPECTED_THEME_SET.issubset(available_theme_set),
            "detail": ",".join(available_themes),
        }
    )
    checks.append(
        {
            "name": "hidden_theme_compatibility_not_publicly_exposed",
            "passed": public_theme_set.issubset(available_theme_set),
            "detail": ",".join(sorted(available_theme_set - public_theme_set)) or "none",
        }
    )
    checks.append(
        {
            "name": "coherence_module_three_theme_contract",
            "passed": frozenset(THEME_SURFACE_COHERENCE_THEMES) == EXPECTED_THEME_SET,
            "detail": "|".join(THEME_SURFACE_COHERENCE_THEMES),
        }
    )

    window.resize(1600, 900)
    window.show()
    _events(application)

    for theme_name in EXPECTED_THEMES:
        window.apply_theme(theme_name)
        _events(application)

        qpalette = window.theme_manager.palette(theme_name)
        is_dark = qpalette.color(QPalette.ColorRole.Window).lightness() < 128
        semantic = palette_for(is_dark=is_dark, concept_key=ACTIVE_CONCEPT)
        stylesheet = application.styleSheet()
        coherence = theme_surface_coherence_stylesheet(
            is_dark=is_dark,
            concept_key=ACTIVE_CONCEPT,
        )

        runtime_canvas = (
            window.application_shell,
            window.left_dock,
            window.right_dock,
            window.left_tabs,
            window.right_tabs,
        )
        runtime_surface = (
            window.queue_workspace,
            window.selected_row_panel,
        )

        checks.append(
            {
                "name": f"{theme_name.lower()}_resolved_mode",
                "passed": window.property("a11ThemeMode") == ("dark" if is_dark else "light"),
                "detail": str(window.property("a11ThemeMode")),
            }
        )
        expected_window = qpalette.color(QPalette.ColorRole.Window).name().lower()
        actual_window = QWidget.palette(window).color(QPalette.ColorRole.Window).name().lower()
        checks.append(
            {
                "name": f"{theme_name.lower()}_qpalette_authority",
                "passed": actual_window == expected_window,
                "detail": f"actual={actual_window};expected={expected_window}",
            }
        )
        checks.append(
            {
                "name": f"{theme_name.lower()}_canvas_surface_family",
                "passed": all(
                    widget.property("a121SurfaceFamily") == "canvas"
                    for widget in runtime_canvas
                ),
                "detail": semantic.canvas,
            }
        )
        checks.append(
            {
                "name": f"{theme_name.lower()}_raised_surface_family",
                "passed": all(
                    widget.property("a121SurfaceFamily") == "surface"
                    for widget in runtime_surface
                ),
                "detail": semantic.surface,
            }
        )
        checks.append(
            {
                "name": f"{theme_name.lower()}_final_overlay_is_semantic_family",
                "passed": coherence in stylesheet
                and f"background:{semantic.canvas}" in coherence
                and f"background:{semantic.surface}" in coherence,
                "detail": f"canvas={semantic.canvas};surface={semantic.surface}",
            }
        )

        filename = f"theme-{theme_name.casefold()}.png"
        evidence.append(_capture(window, output / filename))

    failed = [item for item in checks if not item["passed"]]
    result = {
        "certification_version": CERTIFICATION_VERSION,
        "baseline_commit": EXPECTED_BASELINE_COMMIT,
        "active_concept": ACTIVE_CONCEPT,
        "status": "CERTIFIED" if not failed else "FAILED",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "checks": checks,
        "evidence": evidence,
    }
    (output / "certification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def run_isolated(output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="s-talking-a121-") as temporary:
        temp_root = Path(temporary)
        settings_root = temp_root / "settings"
        runtime_root = temp_root / "runtime"
        settings_root.mkdir(parents=True)
        runtime_root.mkdir(parents=True)

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(settings_root),
        )

        application = QApplication.instance()
        owns_application = application is None
        if application is None:
            application = QApplication(["s-talking-a12.1-certification"])
        font_ok, font_family = ensure_readable_runtime_font(
            application,
            require_explicit_font=True,
        )
        if not font_ok or not font_family:
            raise RuntimeError(
                "Readable UI font is unavailable; screenshot certification cannot continue."
            )
        application.setQuitOnLastWindowClosed(False)

        window = MainWindow(
            create_application_context(
                create_service_container(RuntimeConfig.from_root(runtime_root))
            )
        )
        try:
            return certify_window(window, output)
        finally:
            window.close()
            _events(application)
            if owns_application:
                application.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_isolated(args.output)
    print(f"A12.1 three-theme surface certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
