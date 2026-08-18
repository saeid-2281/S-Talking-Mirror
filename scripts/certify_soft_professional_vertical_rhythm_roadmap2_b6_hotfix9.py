from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("S_TALKING_TEST_FAST_PATH", "1")

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QSizePolicy

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.runtime_font_support import ensure_readable_runtime_font
from app.gui.visual_design_system_v2 import COMPONENTS, TYPOGRAPHY


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Certify B6 Hotfix 9 vertical rhythm and typography.")
    parser.add_argument("--output", required=True, type=Path)
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


def _events(app: QApplication, count: int = 6) -> None:
    for _ in range(count):
        app.processEvents()


def _top_in_shell(window: MainWindow, widget) -> int:  # noqa: ANN001
    return widget.mapTo(window.application_shell, QPoint(0, 0)).y()


def _font_height(widget) -> int:  # noqa: ANN001
    return QFontMetrics(widget.font()).height()


def main() -> int:
    args = _args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="s-talking-b6h9-cert-") as temp:
        root = Path(temp)
        qsettings = root / "qsettings"
        runtime = root / "runtime"
        qsettings.mkdir(parents=True)
        runtime.mkdir(parents=True)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(qsettings))

        app = QApplication.instance() or QApplication(["s-talking-b6-hotfix9-certification"])
        app.setQuitOnLastWindowClosed(False)
        font_ok, font_family = ensure_readable_runtime_font(app, require_explicit_font=True)

        window = MainWindow(
            create_application_context(
                create_service_container(RuntimeConfig.from_root(runtime))
            )
        )
        window.resize(2048, 1140)
        window.main_workspace_modernizer.apply_responsive_mode("wide")
        window.main_workspace_modernizer.reveal_workflow(False)
        window.main_workspace_modernizer.reveal_batch_planning(False)
        window.main_workspace_modernizer.reapply_visual_geometry()

        captures: dict[str, dict[str, object]] = {}
        geometry_by_theme: dict[str, dict[str, object]] = {}
        checks: dict[str, bool] = {}

        for theme in ("Dark", "Light", "System"):
            window.apply_theme(theme)
            window.show()
            window.main_workspace_modernizer.apply_responsive_mode("wide")
            window.main_workspace_modernizer.reveal_workflow(False)
            window.main_workspace_modernizer.reveal_batch_planning(False)
            window.main_workspace_modernizer.reapply_visual_geometry()
            _events(app)

            queue_top = _top_in_shell(window, window.queue_workspace)
            launch_top = _top_in_shell(window, window.generation_status_strip)
            launch_bottom = launch_top + window.generation_status_strip.height()
            summary_top = _top_in_shell(window, window.queue_workspace.summary)
            summary_bottom = summary_top + window.queue_workspace.summary.height()
            shell_gap = queue_top - launch_bottom
            command_gap = window.queue_workspace.command_host.y() - (
                window.queue_workspace.heading.y() + window.queue_workspace.heading.height()
            )
            summary_gap = window.queue_workspace.summary.y() - (
                window.queue_workspace.command_host.y() + window.queue_workspace.command_host.height()
            )
            chrome_top_offset = window.queue_workspace.chrome_host.y()
            heading_top_in_chrome = window.queue_workspace.heading.y()
            chrome_to_body_gap = window.queue_workspace.body_host.y() - (
                window.queue_workspace.chrome_host.y()
                + window.queue_workspace.chrome_host.height()
            )

            control_heights = {
                "queue_search": window.queue_search.height(),
                "queue_status": window.queue_filter.height(),
                "queue_source": window.source_filter.height(),
                "queue_scope": window.scope_selector.height(),
                "queue_order": window.order_selector.height(),
                "use_sort": window.use_sort_button.height(),
                "use_selection": window.use_selection_scope_button.height(),
                "dry_run": window.dry_run_button.height(),
                "retry": window.retry_menu_button.height(),
                "clear_completed": window.clear_completed_button.height(),
                "start": window.generation_status_strip.start_button.height(),
                "preflight": window.generation_status_strip.preflight_button.height(),
                "pause": window.generation_status_strip.pause_button.height(),
                "stop": window.generation_status_strip.stop_button.height(),
            }
            font_heights = {
                "queue_search": _font_height(window.queue_search),
                "dry_run": _font_height(window.dry_run_button),
                "start": _font_height(window.generation_status_strip.start_button),
                "provider": _font_height(window.provider),
                "selected_row_play": _font_height(window.play_output_button),
            }

            geometry_by_theme[theme.casefold()] = {
                "viewport": [window.width(), window.height()],
                "launch_bar_height": window.generation_status_strip.height(),
                "queue_heading_height": window.queue_workspace.heading.height(),
                "queue_command_height": window.queue_workspace.command_host.height(),
                "queue_summary_height": window.queue_workspace.summary.height(),
                "queue_chrome_height": window.queue_workspace.chrome_host.height(),
                "queue_chrome_content_height": window.queue_workspace.chrome_content_height(),
                "queue_chrome_size_hint": window.queue_workspace.root_layout.sizeHint().height(),
                "queue_chrome_top_offset": chrome_top_offset,
                "heading_top_in_chrome": heading_top_in_chrome,
                "queue_chrome_to_body_gap": chrome_to_body_gap,
                "queue_body_height": window.queue_workspace.body_host.height(),
                "launch_to_queue_gap": shell_gap,
                "heading_to_command_gap": command_gap,
                "command_to_summary_gap": summary_gap,
                "collapsed_range_hidden": window.queue_workspace.range_host.isHidden(),
                "collapsed_range_max_height": window.queue_workspace.range_host.maximumHeight(),
                "collapsed_range_layout_index": window.queue_workspace.root_layout.indexOf(
                    window.queue_workspace.range_host
                ),
                "workflow_disclosure_hidden": window.generation_journey.isHidden(),
                "workflow_disclosure_layout_index": window.queue_workspace.root_layout.indexOf(
                    window.generation_journey
                ),
                "batch_disclosure_hidden": window.queue_batch_operations.isHidden(),
                "batch_disclosure_layout_index": window.queue_workspace.root_layout.indexOf(
                    window.queue_batch_operations
                ),
                "launch_to_summary_bottom": summary_bottom - launch_top,
                "control_heights": control_heights,
                "body_font_metric_heights": font_heights,
            }

            prefix = theme.casefold()
            checks[f"{prefix}_launch_to_queue_gap_compact"] = 0 <= shell_gap <= 8
            checks[f"{prefix}_queue_heading_fixed_46"] = window.queue_workspace.heading.height() == 46
            checks[f"{prefix}_queue_command_fixed_80"] = window.queue_workspace.command_host.height() == 80
            checks[f"{prefix}_queue_summary_compact"] = 30 <= window.queue_workspace.summary.height() <= 32
            checks[f"{prefix}_collapsed_range_consumes_zero_height"] = (
                window.queue_workspace.range_host.isHidden()
                and window.queue_workspace.range_host.maximumHeight() == 0
            )
            checks[f"{prefix}_collapsed_range_removed_from_layout"] = (
                window.queue_workspace.root_layout.indexOf(window.queue_workspace.range_host) == -1
            )
            checks[f"{prefix}_collapsed_optional_disclosures_stay_hidden"] = (
                window.generation_journey.isHidden()
                and window.queue_batch_operations.isHidden()
            )
            checks[f"{prefix}_collapsed_optional_disclosures_removed_from_layout"] = (
                window.queue_workspace.root_layout.indexOf(window.generation_journey) == -1
                and window.queue_workspace.root_layout.indexOf(window.queue_batch_operations) == -1
            )
            checks[f"{prefix}_queue_chrome_is_vertically_fixed"] = (
                window.queue_workspace.chrome_host.sizePolicy().verticalPolicy()
                == QSizePolicy.Policy.Fixed
                and window.queue_workspace.chrome_host.height()
                == window.queue_workspace.chrome_content_height()
            )
            checks[f"{prefix}_queue_chrome_anchored_at_shell_top"] = (
                0 <= chrome_top_offset <= 2
                and 0 <= heading_top_in_chrome <= 2
            )
            checks[f"{prefix}_queue_body_owns_vertical_surplus"] = (
                window.queue_workspace.body_host.sizePolicy().verticalPolicy()
                == QSizePolicy.Policy.Expanding
                and 0 <= chrome_to_body_gap <= 8
            )
            checks[f"{prefix}_heading_to_command_gap_compact"] = 0 <= command_gap <= 8
            checks[f"{prefix}_command_to_summary_gap_compact"] = 0 <= summary_gap <= 8
            checks[f"{prefix}_launch_to_summary_under_220"] = summary_bottom - launch_top <= 220
            checks[f"{prefix}_all_center_controls_34"] = set(control_heights.values()) == {COMPONENTS.control_compact_height}
            checks[f"{prefix}_body_font_metrics_consistent"] = max(font_heights.values()) - min(font_heights.values()) <= 2

            captures[f"{prefix}_main"] = _capture(window, output / f"{prefix}-main.png")

        # Explicit disclosure composition is also structural.  Verify one
        # representative Wide-mode Batch plan composition before restoring the
        # collapsed screenshot state.
        window.main_workspace_modernizer.reveal_workflow(False)
        window.main_workspace_modernizer.reveal_batch_planning(True)
        _events(app)
        root_layout = window.queue_workspace.root_layout
        batch_index = root_layout.indexOf(window.queue_batch_operations)
        range_index = root_layout.indexOf(window.queue_workspace.range_host)
        command_index = root_layout.indexOf(window.queue_workspace.command_host)
        batch_gap = window.queue_batch_operations.y() - (
            window.queue_workspace.heading.y() + window.queue_workspace.heading.height()
        )
        range_gap = window.queue_workspace.range_host.y() - (
            window.queue_batch_operations.y() + window.queue_batch_operations.height()
        )
        explicit_command_gap = window.queue_workspace.command_host.y() - (
            window.queue_workspace.range_host.y() + window.queue_workspace.range_host.height()
        )
        checks["explicit_batch_structural_order"] = (
            root_layout.indexOf(window.generation_journey) == -1
            and batch_index == 1
            and range_index == 2
            and command_index == 3
        )
        checks["explicit_batch_vertical_gaps_compact"] = (
            0 <= batch_gap <= 8
            and 0 <= range_gap <= 8
            and 0 <= explicit_command_gap <= 8
        )
        window.main_workspace_modernizer.reveal_batch_planning(False)
        _events(app)

        checks["font_available"] = bool(font_ok and font_family)
        checks["selected_body_scale_is_13"] = TYPOGRAPHY.body == 13
        checks["selected_caption_scale_is_11"] = TYPOGRAPHY.caption == 11
        checks["selected_section_scale_is_14"] = TYPOGRAPHY.section == 14
        checks["selected_control_height_is_34"] = COMPONENTS.control_compact_height == 34

        failed = [name for name, passed in checks.items() if not passed]
        payload = {
            "schema_version": 1,
            "phase": "Roadmap 2 B6 Hotfix 3 Hotfix 9",
            "status": "CERTIFIED" if not failed else "FAILED",
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "failed_checks": failed,
            "font": {"usable": font_ok, "family": font_family},
            "contract": {
                "caption_px": TYPOGRAPHY.caption,
                "label_px": TYPOGRAPHY.label,
                "body_px": TYPOGRAPHY.body,
                "section_px": TYPOGRAPHY.section,
                "title_px": TYPOGRAPHY.title,
                "control_height": COMPONENTS.control_compact_height,
            },
            "geometry": geometry_by_theme,
            "captures": captures,
            "scope": "main-shell vertical rhythm, queue height efficiency, and typography/control-size unification",
        }
        (output / "certification.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Roadmap 2 B6 Hotfix 9 certification: {payload['status']}")
        print(f"Checks: {len(checks) - len(failed)}/{len(checks)}")
        print(f"Font: {font_family}")
        print(f"Evidence: {output}")
        if failed:
            print("Failed checks:")
            for name in failed:
                print(f"  - {name}")
        window.close()
        _events(app)
        return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
