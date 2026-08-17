from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QSize
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QLabel,
    QSplitter,
    QToolButton,
    QWidget,
)

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.runtime_font_support import ensure_readable_runtime_font
from app.gui.theme_accessibility_v2 import (
    assert_soft_professional_contrast_contract,
    soft_professional_contrast_audit,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT


CERTIFICATION_VERSION = "roadmap2-a12-v1"
EXPECTED_BASELINE_COMMIT = "eec5ade2b2017b17b45248e68c174801bebd353a"
EXPECTED_ACTIVE_CONCEPT = "soft_professional"
EVIDENCE_SURFACES = (
    "main-light.png",
    "generation-monitor-light.png",
    "provider-accounts-light.png",
    "main-dark.png",
)

PUBLIC_VISUAL_HANDLES = (
    "application_shell",
    "main_toolbar",
    "queue_workspace",
    "cards",
    "provider_overview",
    "selected_row_panel",
    "monitor_dock",
    "right_tabs",
    "activity_tabs",
    "text_studio",
    "table",
)


@dataclass(frozen=True)
class CertificationCheck:
    name: str
    passed: bool
    detail: str


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check(checks: list[CertificationCheck], name: str, condition: bool, detail: str) -> None:
    checks.append(CertificationCheck(name=name, passed=bool(condition), detail=str(detail)))


def _capture(widget: QWidget, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError(f"Unable to capture visual evidence: {output_path.name}")
    if not pixmap.save(str(output_path), "PNG"):
        raise RuntimeError(f"Unable to save visual evidence: {output_path}")
    return {
        "file": output_path.name,
        "width": pixmap.width(),
        "height": pixmap.height(),
        "sha256": _file_sha256(output_path),
    }


def _process_events(application: QApplication, count: int = 3) -> None:
    for _ in range(max(1, int(count))):
        application.processEvents()


def _monitor_index(window: MainWindow) -> int:
    return next(
        index
        for index in range(window.right_tabs.count())
        if window.right_tabs.tabText(index).strip().casefold() == "generation monitor"
    )


def _metric_contract(window: MainWindow) -> tuple[bool, str]:
    expected = {"files", "pending", "running", "done", "failed", "quota", "eta"}
    missing = sorted(expected.difference(window.cards))
    if missing:
        return False, f"missing metric cards: {', '.join(missing)}"
    for key in sorted(expected):
        card = window.cards[key]
        if card.property("visualFidelityRadius") != 12:
            return False, f"{key}: radius property={card.property('visualFidelityRadius')!r}"
        if "border-radius: 12px" not in card.styleSheet():
            return False, f"{key}: 12px radius stylesheet missing"
        original_active = card.property("active")
        card.set_active(True)
        if "border-radius: 12px" not in card.styleSheet():
            return False, f"{key}: active radius changed"
        card.set_active(False)
        if original_active is True:
            card.set_active(True)
    return True, "7 operational cards keep one 12px Soft Professional radius"


def _toolbar_contract(window: MainWindow) -> tuple[bool, str]:
    hardener = window.visual_fidelity_hardener
    if window.main_toolbar.iconSize() != QSize(24, 24):
        return False, f"toolbar iconSize={window.main_toolbar.iconSize()}"
    for action_name, icon_name in hardener.TOOLBAR_ICON_MAP.items():
        action = window.actions_by_name.get(action_name)
        if action is None:
            return False, f"missing toolbar action: {action_name}"
        if action.icon().isNull():
            return False, f"null toolbar icon: {action_name}"
        if action.property("visualFidelityIcon") != icon_name:
            return False, f"non-canonical icon mapping: {action_name}"
    buttons = window.main_toolbar.findChildren(QToolButton)
    if not buttons:
        return False, "toolbar exposes no QToolButton controls"
    if any(button.iconSize() != QSize(24, 24) for button in buttons):
        return False, "toolbar button icon sizes are not uniform"
    return True, f"{len(hardener.TOOLBAR_ICON_MAP)} canonical actions at 24x24"


def _provider_overview_contract(window: MainWindow) -> tuple[bool, str]:
    overview = window.provider_overview
    window.set_provider_status("Provider account state changed and requires attention.")
    window.visual_fidelity_hardener.refresh_provider_overview()
    if overview.property("visualFidelityProviderOverview") is not True:
        return False, "provider overview visual-fidelity property missing"
    if overview.minimumWidth() != 0:
        return False, f"provider overview minimumWidth={overview.minimumWidth()}"
    for label in overview.findChildren(QLabel):
        if label.minimumWidth() != 0:
            return False, f"provider label retains minimum width: {label.objectName()!r}"
        if len(label.text().strip()) > 22 and not label.wordWrap():
            return False, f"long provider label does not wrap: {label.text()[:32]!r}"
    return True, "narrow provider dock accepts wrapped/elided long state"


def _provider_accounts_contract(
    window: MainWindow,
    application: QApplication,
) -> tuple[QDialog, bool, str]:
    dialog = window.open_provider_accounts()
    _process_events(application)
    window.visual_fidelity_hardener.polish_dialog(dialog)
    _process_events(application)

    splitter = dialog.findChild(QSplitter, "providerAccountsSplitter")
    details = dialog.findChild(QWidget, "providerAccountDetails")
    if splitter is None or details is None:
        return dialog, False, "Provider Accounts splitter/details surface missing"
    buttons = details.findChildren(QAbstractButton)
    condition = (
        dialog.minimumWidth() >= 1160
        and dialog.minimumHeight() >= 720
        and details.minimumWidth() >= 420
        and not splitter.childrenCollapsible()
        and buttons
        and all(button.minimumWidth() >= 78 for button in buttons)
        and all(button.minimumHeight() >= 34 for button in buttons)
    )
    detail = (
        f"dialog>={dialog.minimumWidth()}x{dialog.minimumHeight()}, "
        f"details>={details.minimumWidth()}px, actions={len(buttons)}"
    )
    return dialog, bool(condition), detail


def _theme_contract(window: MainWindow, theme_name: str) -> tuple[bool, str]:
    application = QApplication.instance()
    if application is None:
        return False, "QApplication is unavailable"
    window.apply_theme(theme_name)
    _process_events(application)
    is_dark = application.palette().color(QPalette.ColorRole.Window).lightness() < 128
    expected_mode = "dark" if is_dark else "light"
    actual_mode = str(window.property("a11ThemeMode") or "")
    resolved = str(window.property("a11ResolvedTheme") or "")
    condition = actual_mode == expected_mode and resolved == theme_name
    return condition, f"{theme_name}: palette={expected_mode}, semantic={actual_mode}, resolved={resolved}"


def certify_window(
    window: MainWindow,
    output_dir: Path,
    *,
    baseline_commit: str = EXPECTED_BASELINE_COMMIT,
) -> dict[str, Any]:
    """Certify the real A11.1 UI and write screenshot + machine-readable evidence."""

    application = QApplication.instance()
    if application is None:
        raise RuntimeError("A QApplication is required for A12 visual certification.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: list[CertificationCheck] = []
    evidence: list[dict[str, Any]] = []

    font_ok, font_family = ensure_readable_runtime_font(
        application,
        require_explicit_font=True,
    )
    _check(
        checks,
        "readable_runtime_font",
        font_ok and bool(font_family),
        f"family={font_family or 'unavailable'}",
    )

    assert_soft_professional_contrast_contract()
    light_audit = soft_professional_contrast_audit(is_dark=False)
    dark_audit = soft_professional_contrast_audit(is_dark=True)

    _check(
        checks,
        "selected_visual_direction",
        ACTIVE_CONCEPT == EXPECTED_ACTIVE_CONCEPT,
        f"ACTIVE_CONCEPT={ACTIVE_CONCEPT}",
    )
    _check(
        checks,
        "light_wcag_semantic_contrast",
        all(item.passed for item in light_audit),
        ", ".join(f"{item.name}={item.ratio:.2f}" for item in light_audit),
    )
    _check(
        checks,
        "dark_wcag_semantic_contrast",
        all(item.passed for item in dark_audit),
        ", ".join(f"{item.name}={item.ratio:.2f}" for item in dark_audit),
    )
    _check(
        checks,
        "modernization_stack",
        all(
            hasattr(window, attribute)
            for attribute in (
                "main_workspace_modernizer",
                "dialog_form_modernizer",
                "theme_accessibility_modernizer",
                "visual_fidelity_hardener",
            )
        ),
        "A9/A10/A11/A11.1 runtime modernizers are installed",
    )
    _check(
        checks,
        "public_visual_handles",
        all(hasattr(window, handle) for handle in PUBLIC_VISUAL_HANDLES),
        ", ".join(PUBLIC_VISUAL_HANDLES),
    )

    window.resize(1600, 900)
    window.show()
    _process_events(application, 4)

    light_ok, light_detail = _theme_contract(window, "Light")
    _check(checks, "light_theme_resolution", light_ok, light_detail)

    toolbar_ok, toolbar_detail = _toolbar_contract(window)
    _check(checks, "toolbar_icon_fidelity", toolbar_ok, toolbar_detail)

    metric_ok, metric_detail = _metric_contract(window)
    _check(checks, "metric_radius_stability", metric_ok, metric_detail)

    provider_ok, provider_detail = _provider_overview_contract(window)
    _check(checks, "provider_overview_fit", provider_ok, provider_detail)

    top_titles = [
        widget.windowTitle().strip().casefold()
        for widget in application.topLevelWidgets()
        if isinstance(widget, QWidget)
    ]
    _check(
        checks,
        "no_detached_scope_order_window",
        "scope & order" not in top_titles,
        f"top-level windows={len(top_titles)}",
    )

    evidence.append(_capture(window, output_dir / "main-light.png"))

    monitor_index = _monitor_index(window)
    window.right_tabs.setCurrentIndex(monitor_index)
    window.visual_fidelity_hardener.refresh_monitor()
    _process_events(application, 4)
    monitor_ok = (
        280 <= window.monitor_dock.minimumWidth() <= 300
        and 320 <= window.monitor_dock.width() <= 340
        and window.monitor_dock.maximumWidth() <= 340
        and window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    )
    _check(
        checks,
        "generation_monitor_fit",
        monitor_ok,
        (
            f"minimum-api={window.monitor_dock.minimumWidth()}px, "
            f"actual={window.monitor_dock.width()}px, "
            f"maximum={window.monitor_dock.maximumWidth()}px"
        ),
    )
    evidence.append(_capture(window, output_dir / "generation-monitor-light.png"))

    dialog, accounts_ok, accounts_detail = _provider_accounts_contract(window, application)
    _check(checks, "provider_accounts_details_fit", accounts_ok, accounts_detail)
    evidence.append(_capture(dialog, output_dir / "provider-accounts-light.png"))
    dialog.close()
    dialog.deleteLater()
    _process_events(application, 4)

    dark_ok, dark_detail = _theme_contract(window, "Dark")
    _check(checks, "dark_theme_resolution", dark_ok, dark_detail)
    evidence.append(_capture(window, output_dir / "main-dark.png"))

    system_ok, system_detail = _theme_contract(window, "System")
    _check(checks, "system_theme_palette_resolution", system_ok, system_detail)

    evidence_names = tuple(item["file"] for item in evidence)
    _check(
        checks,
        "required_visual_evidence",
        evidence_names == EVIDENCE_SURFACES,
        ", ".join(evidence_names),
    )
    _check(
        checks,
        "evidence_is_nonempty",
        all(item["width"] >= 800 and item["height"] >= 600 and item["sha256"] for item in evidence),
        "; ".join(f"{item['file']}={item['width']}x{item['height']}" for item in evidence),
    )

    failed = [item for item in checks if not item.passed]
    result = {
        "certification_version": CERTIFICATION_VERSION,
        "status": "CERTIFIED" if not failed else "FAILED",
        "baseline_commit": baseline_commit,
        "active_concept": ACTIVE_CONCEPT,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "checks": [asdict(item) for item in checks],
        "evidence": evidence,
    }

    json_path = output_dir / "certification.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_html_report(output_dir / "index.html", result)

    return result


def _write_html_report(path: Path, result: dict[str, Any]) -> None:
    checks_html = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(item['name']))}</td>"
        f"<td>{'PASS' if item['passed'] else 'FAIL'}</td>"
        f"<td>{html.escape(str(item['detail']))}</td>"
        "</tr>"
        for item in result["checks"]
    )
    evidence_html = "\n".join(
        "<section>"
        f"<h2>{html.escape(str(item['file']))}</h2>"
        f"<p>{item['width']} × {item['height']} · SHA-256 {html.escape(str(item['sha256']))}</p>"
        f"<img src=\"{html.escape(str(item['file']))}\" alt=\"{html.escape(str(item['file']))}\">"
        "</section>"
        for item in result["evidence"]
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>S-Talking Roadmap 2 A12 Visual Certification</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 32px; background: #f7f7f5; color: #1c211f; }}
main {{ max-width: 1280px; margin: auto; }}
header, section, table {{ background: white; border: 1px solid #dfe3df; border-radius: 14px; }}
header, section {{ padding: 18px; margin-bottom: 18px; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 18px; overflow: hidden; }}
th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #eceeeb; vertical-align: top; }}
img {{ width: 100%; height: auto; border-radius: 10px; border: 1px solid #e2e5e1; }}
.pass {{ color: #246b4b; }}
.fail {{ color: #a33f3f; }}
</style>
</head>
<body><main>
<header>
<h1>S-Talking Roadmap 2 A12 — Final Product UX & Visual Certification</h1>
<p>Status: <strong class="{'pass' if result['status'] == 'CERTIFIED' else 'fail'}">{result['status']}</strong></p>
<p>Baseline: {html.escape(str(result['baseline_commit']))}<br>
Visual direction: {html.escape(str(result['active_concept']))}<br>
Checks: {result['checks_passed']} / {result['checks_total']}</p>
</header>
<table>
<thead><tr><th>Check</th><th>Result</th><th>Evidence</th></tr></thead>
<tbody>{checks_html}</tbody>
</table>
{evidence_html}
</main></body></html>
"""
    path.write_text(document, encoding="utf-8")


def run_isolated_certification(output_dir: Path) -> dict[str, Any]:
    """Run A12 without reading or writing the operator's real QSettings/profile data."""

    with tempfile.TemporaryDirectory(prefix="s-talking-a12-cert-") as temporary:
        temporary_root = Path(temporary)
        settings_root = temporary_root / "settings"
        runtime_root = temporary_root / "runtime"
        settings_root.mkdir(parents=True, exist_ok=True)
        runtime_root.mkdir(parents=True, exist_ok=True)

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(settings_root),
        )

        application = QApplication.instance()
        owns_application = application is None
        if application is None:
            application = QApplication(["s-talking-a12-certification"])
        application.setQuitOnLastWindowClosed(False)

        window = MainWindow(
            create_application_context(
                create_service_container(RuntimeConfig.from_root(runtime_root))
            )
        )
        try:
            result = certify_window(window, output_dir)
        finally:
            window.close()
            _process_events(application, 4)
            if owns_application:
                application.quit()
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate S-Talking Roadmap 2 A12 product UX/visual certification evidence."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for certification.json, index.html and PNG evidence.",
    )
    args = parser.parse_args()

    result = run_isolated_certification(args.output)
    print(f"A12 visual certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
