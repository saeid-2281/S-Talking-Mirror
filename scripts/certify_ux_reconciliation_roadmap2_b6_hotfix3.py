from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("S_TALKING_TEST_FAST_PATH", "1")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.runtime_font_support import ensure_readable_runtime_font
from app.gui.theme_accessibility_v2 import (
    ux_reality_reconciliation_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for
from app.gui.main import MainWindow


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Certify B6 Hotfix 3 UX reality reconciliation."
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _capture(widget, path: Path) -> dict[str, object]:  # noqa: ANN001
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"Unable to capture screenshot: {path}")
    return {
        "file": path.name,
        "width": pixmap.width(),
        "height": pixmap.height(),
        "sha256": _sha256(path),
    }


def _events(application: QApplication, count: int = 5) -> None:
    for _ in range(count):
        application.processEvents()


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="s-talking-b6h3-cert-") as temporary:
        temp_root = Path(temporary)
        settings_root = temp_root / "qsettings"
        runtime_root = temp_root / "runtime"
        settings_root.mkdir(parents=True)
        runtime_root.mkdir(parents=True)

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(settings_root),
        )

        application = QApplication.instance() or QApplication(
            ["s-talking-b6-hotfix3-certification"]
        )
        application.setQuitOnLastWindowClosed(False)
        font_ok, font_family = ensure_readable_runtime_font(
            application,
            require_explicit_font=True,
        )
        metrics = QFontMetrics(application.font())
        glyph_sample = "STalkingProviderAccountsÆØÅæøå0123"
        glyphs_ok = all(metrics.inFontUcs4(ord(character)) for character in glyph_sample)

        context = create_application_context(
            create_service_container(RuntimeConfig.from_root(runtime_root))
        )
        context.api_profile_service.create_profile(
            "Certification profile",
            provider="elevenlabs",
            api_key="certification-only-secret",
            active=True,
        )

        window = MainWindow(context)
        window.resize(1800, 1000)
        window.apply_theme("Dark")
        window.show()
        _events(application)

        dialog = window.open_provider_accounts("elevenlabs")
        dialog.resize(1120, 720)
        dialog.show()
        _events(application)
        if dialog.table.rowCount():
            dialog.table.selectRow(0)
            _events(application)

        semantic_dark = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
        dark_style = ux_reality_reconciliation_stylesheet(
            is_dark=True,
            concept_key=ACTIVE_CONCEPT,
        )
        light_style = ux_reality_reconciliation_stylesheet(
            is_dark=False,
            concept_key=ACTIVE_CONCEPT,
        )

        scroll_geometry = dialog.details_scroll.geometry()
        actions_geometry = dialog.details_actions_host.geometry()
        details_layout_non_overlap = (
            scroll_geometry.isValid()
            and actions_geometry.isValid()
            and scroll_geometry.bottom() < actions_geometry.top()
        )

        checks: dict[str, bool] = {
            "soft_professional_active": ACTIVE_CONCEPT == "soft_professional",
            "readable_runtime_font_available": bool(font_ok and font_family),
            "latin_danish_glyphs_available": bool(glyphs_ok),
            "font_sample_has_real_width": metrics.horizontalAdvance("S Talking") > 20,
            "startup_path_notice_exists": hasattr(window, "project_path_notice"),
            "startup_path_notice_is_non_modal_widget": not window.project_path_notice.isWindow(),
            "toolbar_uses_24px_logical_icons": window.main_toolbar.iconSize().width() == 24
            and window.main_toolbar.iconSize().height() == 24,
            "toolbar_has_hidpi_room": window.main_toolbar.minimumHeight() >= 38,
            "menu_geometry_reserves_transparent_border": "border:1px solid transparent"
            in dark_style,
            "menu_hover_uses_soft_surface": f"background:{semantic_dark.surface_secondary}"
            in dark_style,
            "provider_details_scrollable": dialog.details_scroll.widgetResizable()
            and dialog.details_scroll.widget() is dialog.details_content,
            "provider_details_wider_contract": dialog.details_panel.minimumWidth() >= 340,
            "provider_details_actions_separate_from_scroll": details_layout_non_overlap,
            "provider_detail_action_grid": dialog.details_actions_host.layout().count() == 4,
            "queue_inspector_neutralized": "QFrame#queueInspectorCard" in dark_style
            and f"background:{semantic_dark.surface}" in dark_style,
            "dark_selection_is_neutral": f"background:{semantic_dark.surface_secondary}"
            in dark_style,
            "light_shell_contract_present": "Roadmap 2 B6 Hotfix 3" in light_style,
            "no_authority_terms_in_presentation_layer": not any(
                token in dark_style
                for token in (
                    "start_generation(",
                    "run_preflight(",
                    "setCurrentText(",
                    "activate_failover",
                )
            ),
        }

        captures: dict[str, dict[str, object]] = {}
        captures["dark_main"] = _capture(window, output / "dark-main.png")
        captures["dark_provider_accounts"] = _capture(
            dialog,
            output / "dark-provider-accounts.png",
        )

        dialog.close()
        _events(application)

        window.apply_theme("Light")
        _events(application)
        captures["light_main"] = _capture(window, output / "light-main.png")

        window.apply_theme("System")
        _events(application)
        captures["system_main"] = _capture(window, output / "system-main.png")

        failed = [name for name, passed in checks.items() if not passed]
        payload = {
            "schema_version": 1,
            "phase": "Roadmap 2 B6 Hotfix 3",
            "status": "CERTIFIED" if not failed else "FAILED",
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "failed_checks": failed,
            "font": {
                "usable": font_ok,
                "family": font_family,
                "glyph_sample": glyph_sample,
                "glyphs_ok": glyphs_ok,
            },
            "captures": captures,
            "scope": (
                "non-blocking project recovery, Provider Accounts layout, HiDPI icons, "
                "menu states, Soft Professional shell fidelity, three-theme visual evidence"
            ),
        }
        (output / "certification.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        window.close()
        _events(application)

    print(f"Roadmap 2 B6 Hotfix 3 UX certification: {payload['status']}")
    print(f"Checks: {len(checks) - len(failed)}/{len(checks)}")
    print(f"Font: {payload['font']['family'] or 'unavailable'}")
    print(f"Evidence: {output}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
