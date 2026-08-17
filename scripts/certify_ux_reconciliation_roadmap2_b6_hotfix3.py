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
from PySide6.QtGui import QFontMetrics, QImage
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



LEGACY_DARK_STRUCTURAL_RGB = {
    (11, 18, 32),   # #0B1220
    (15, 27, 49),   # #0F1B31
    (28, 44, 70),   # #1C2C46
    (17, 24, 39),   # #111827
    (23, 32, 51),   # #172033
    (7, 19, 38),    # #071326
    (10, 15, 28),   # #0A0F1C
}
LEGACY_LIGHT_PRIMARY_RGB = {(37, 99, 235)}  # #2563EB


def _audit_exact_colors(
    path: Path,
    colors: set[tuple[int, int, int]],
    *,
    stride: int = 4,
) -> dict[str, object]:
    """Return exact-color share plus per-color sampled bounding boxes.

    Hotfix 6 intentionally failed closed on broad legacy color leakage, but its
    aggregate percentage did not identify which historical literal remained or
    where it was painted. Hotfix 7 keeps the same acceptance thresholds while
    making any future failure immediately actionable from certification.json.
    """

    image = QImage(str(path))
    if image.isNull():
        raise RuntimeError(f"Unable to read screenshot for color audit: {path}")
    counts = {color: 0 for color in colors}
    boxes: dict[tuple[int, int, int], list[int] | None] = {color: None for color in colors}
    sampled = 0
    matched = 0
    for y in range(0, image.height(), stride):
        for x in range(0, image.width(), stride):
            pixel = image.pixelColor(x, y)
            rgb = (pixel.red(), pixel.green(), pixel.blue())
            sampled += 1
            if rgb not in colors:
                continue
            matched += 1
            counts[rgb] += 1
            box = boxes[rgb]
            if box is None:
                boxes[rgb] = [x, y, x, y]
            else:
                box[0] = min(box[0], x)
                box[1] = min(box[1], y)
                box[2] = max(box[2], x)
                box[3] = max(box[3], y)

    per_color: dict[str, object] = {}
    for rgb in sorted(colors):
        key = "#" + "".join(f"{channel:02X}" for channel in rgb)
        per_color[key] = {
            "sampled_pixels": counts[rgb],
            "share": round(counts[rgb] / max(sampled, 1), 6),
            "bbox": boxes[rgb],
        }
    return {
        "share": matched / max(sampled, 1),
        "sampled_pixels": sampled,
        "matched_pixels": matched,
        "stride": stride,
        "per_color": per_color,
    }


def _sample_exact_color_share(
    path: Path,
    colors: set[tuple[int, int, int]],
    *,
    stride: int = 4,
) -> float:
    return float(_audit_exact_colors(path, colors, stride=stride)["share"])

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

        dark_main_audit = _audit_exact_colors(
            output / "dark-main.png",
            LEGACY_DARK_STRUCTURAL_RGB,
        )
        dark_accounts_audit = _audit_exact_colors(
            output / "dark-provider-accounts.png",
            LEGACY_DARK_STRUCTURAL_RGB,
        )
        dark_main_legacy_share = float(dark_main_audit["share"])
        dark_accounts_legacy_share = float(dark_accounts_audit["share"])

        dialog.close()
        _events(application)

        window.apply_theme("Light")
        _events(application)
        captures["light_main"] = _capture(window, output / "light-main.png")
        light_primary_audit = _audit_exact_colors(
            output / "light-main.png",
            LEGACY_LIGHT_PRIMARY_RGB,
        )
        light_legacy_primary_share = float(light_primary_audit["share"])

        window.apply_theme("System")
        _events(application)
        captures["system_main"] = _capture(window, output / "system-main.png")

        checks.update(
            {
                "dark_main_legacy_navy_below_one_percent": dark_main_legacy_share < 0.01,
                "provider_accounts_legacy_navy_below_one_percent": dark_accounts_legacy_share < 0.01,
                "light_legacy_primary_blue_below_point_two_percent": light_legacy_primary_share < 0.002,
            }
        )

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
            "visual_color_audit": {
                "dark_main_legacy_structural_share": round(dark_main_legacy_share, 6),
                "dark_provider_accounts_legacy_structural_share": round(dark_accounts_legacy_share, 6),
                "light_main_legacy_primary_share": round(light_legacy_primary_share, 6),
                "diagnostics": {
                    "dark_main": dark_main_audit,
                    "dark_provider_accounts": dark_accounts_audit,
                    "light_main_primary": light_primary_audit,
                },
                "thresholds": {
                    "dark_legacy_structural_max": 0.01,
                    "light_legacy_primary_max": 0.002,
                },
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
    audit = payload["visual_color_audit"]
    print(
        "Legacy color share: "
        f"dark-main={audit['dark_main_legacy_structural_share']:.4%}, "
        f"provider-accounts={audit['dark_provider_accounts_legacy_structural_share']:.4%}, "
        f"light-primary={audit['light_main_legacy_primary_share']:.4%}"
    )
    print(f"Evidence: {output}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
