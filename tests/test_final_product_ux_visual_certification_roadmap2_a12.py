from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QAbstractButton, QSplitter, QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme_accessibility_v2 import soft_professional_contrast_audit
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT
from scripts.certify_product_ux_visual_roadmap2_a12 import (
    CERTIFICATION_VERSION,
    EVIDENCE_SURFACES,
    EXPECTED_ACTIVE_CONCEPT,
    EXPECTED_BASELINE_COMMIT,
    PUBLIC_VISUAL_HANDLES,
    certify_window,
)


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_a12_locks_certification_to_official_a111_baseline() -> None:
    assert CERTIFICATION_VERSION == "roadmap2-a12-v1"
    assert EXPECTED_BASELINE_COMMIT == "eec5ade2b2017b17b45248e68c174801bebd353a"


def test_a12_certifies_soft_professional_as_final_visual_direction() -> None:
    assert EXPECTED_ACTIVE_CONCEPT == "soft_professional"
    assert ACTIVE_CONCEPT == EXPECTED_ACTIVE_CONCEPT


def test_a12_light_and_dark_semantic_contrast_contracts_are_green() -> None:
    for is_dark in (False, True):
        audit = soft_professional_contrast_audit(is_dark=is_dark)
        assert audit
        assert all(item.passed for item in audit)


def test_a12_required_visual_evidence_surface_contract_is_complete() -> None:
    assert EVIDENCE_SURFACES == (
        "main-light.png",
        "generation-monitor-light.png",
        "provider-accounts-light.png",
        "main-dark.png",
    )


def test_a12_certifier_is_non_authoritative_and_credential_isolated() -> None:
    source = inspect.getsource(
        __import__(
            "scripts.certify_product_ux_visual_roadmap2_a12",
            fromlist=["run_isolated_certification"],
        )
    )
    assert "QSettings.setDefaultFormat(QSettings.Format.IniFormat)" in source
    assert "QSettings.setPath(" in source
    assert "tempfile.TemporaryDirectory" in source
    assert "start_generation(" not in source
    assert "run_preflight(" not in source
    assert "setCurrentText(" not in source
    assert "api-profiles.json" not in source
    assert "workspace-profiles.json" not in source


def test_a12_runtime_stack_contains_a9_through_a111_modernizers(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    assert hasattr(window, "main_workspace_modernizer")
    assert hasattr(window, "dialog_form_modernizer")
    assert hasattr(window, "theme_accessibility_modernizer")
    assert hasattr(window, "visual_fidelity_hardener")
    window.close()


def test_a12_public_visual_handles_remain_available(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    assert all(hasattr(window, handle) for handle in PUBLIC_VISUAL_HANDLES)
    window.close()


def test_a12_toolbar_and_metric_components_match_final_fidelity_contract(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    hardener = window.visual_fidelity_hardener

    assert window.main_toolbar.iconSize() == QSize(20, 20)
    assert window.main_toolbar.property("visualFidelityIcons") == "canonical"
    for action_name, icon_name in hardener.TOOLBAR_ICON_MAP.items():
        action = window.actions_by_name[action_name]
        assert not action.icon().isNull()
        assert action.property("visualFidelityIcon") == icon_name

    for key in ("files", "pending", "running", "done", "failed", "quota", "eta"):
        card = window.cards[key]
        assert card.property("visualFidelityRadius") == 12
        card.set_active(True)
        qt_app.processEvents()
        assert "border-radius: 12px" in card.styleSheet()
        card.set_active(False)
    window.close()


def test_a12_generation_monitor_preserves_api_and_real_width_contract(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.resize(1600, 900)
    window.show()
    qt_app.processEvents()

    index = next(
        index
        for index in range(window.right_tabs.count())
        if window.right_tabs.tabText(index) == "Generation Monitor"
    )
    window.right_tabs.setCurrentIndex(index)
    window.visual_fidelity_hardener.refresh_monitor()
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.maximumWidth() <= 340
    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    window.close()


def test_a12_provider_accounts_details_remain_readable(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = window.open_provider_accounts()
    qt_app.processEvents()
    window.visual_fidelity_hardener.polish_dialog(dialog)
    qt_app.processEvents()

    splitter = dialog.findChild(QSplitter, "providerAccountsSplitter")
    details = dialog.findChild(QWidget, "providerAccountDetails")
    assert splitter is not None
    assert details is not None
    assert dialog.minimumWidth() >= 1160
    assert dialog.minimumHeight() >= 720
    assert details.minimumWidth() >= 420
    assert splitter.childrenCollapsible() is False

    buttons = details.findChildren(QAbstractButton)
    assert buttons
    assert all(button.minimumWidth() >= 78 for button in buttons)
    assert all(button.minimumHeight() >= 34 for button in buttons)
    dialog.close()
    window.close()


def test_a12_light_dark_and_system_resolution_remain_palette_driven(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    for theme_name in ("Light", "Dark", "System"):
        window.apply_theme(theme_name)
        qt_app.processEvents()
        is_dark = qt_app.palette().color(QPalette.ColorRole.Window).lightness() < 128
        assert window.property("a11ThemeMode") == ("dark" if is_dark else "light")
        assert window.property("a11ResolvedTheme") == theme_name
    window.close()


def test_a12_no_detached_scope_order_window_survives_final_workspace(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()
    titles = {
        widget.windowTitle().strip().casefold()
        for widget in qt_app.topLevelWidgets()
        if hasattr(widget, "windowTitle")
    }
    assert "scope & order" not in titles
    window.close()


def test_a12_end_to_end_runtime_certification_writes_reviewable_evidence(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path / "runtime")
    output = tmp_path / "evidence"

    result = certify_window(window, output)
    qt_app.processEvents()

    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert result["checks_passed"] == result["checks_total"]
    assert result["baseline_commit"] == EXPECTED_BASELINE_COMMIT
    assert result["active_concept"] == "soft_professional"

    assert (output / "certification.json").is_file()
    assert (output / "index.html").is_file()
    for filename in EVIDENCE_SURFACES:
        path = output / filename
        assert path.is_file()
        assert path.stat().st_size > 10_000

    payload = json.loads((output / "certification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "CERTIFIED"
    assert len(payload["evidence"]) == len(EVIDENCE_SURFACES)
    window.close()


def test_a12_report_contract_surfaces_all_required_review_points() -> None:
    source = inspect.getsource(
        __import__(
            "scripts.certify_product_ux_visual_roadmap2_a12",
            fromlist=["certify_window"],
        ).certify_window
    )
    for check_name in (
        "toolbar_icon_fidelity",
        "metric_radius_stability",
        "provider_overview_fit",
        "no_detached_scope_order_window",
        "generation_monitor_fit",
        "provider_accounts_details_fit",
        "light_theme_resolution",
        "dark_theme_resolution",
        "system_theme_palette_resolution",
    ):
        assert check_name in source
