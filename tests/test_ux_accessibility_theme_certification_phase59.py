from __future__ import annotations

import json
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.ux_accessibility_certification_service import (
    UxAccessibilityCertificationService,
)


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _themes() -> dict[str, dict[str, str]]:
    from app.gui.theme import DARK_TOKENS, GRAPHITE_TOKENS, LIGHT_TOKENS

    return {
        "Dark": dict(DARK_TOKENS),
        "Graphite": dict(GRAPHITE_TOKENS),
        "Light": dict(LIGHT_TOKENS),
    }


def test_phase59_theme_matrix_passes_selection_text_and_focus_contrast(tmp_path: Path) -> None:
    service = UxAccessibilityCertificationService(_runtime(tmp_path))
    results, gates = service.audit_theme_tokens(_themes())
    assert len(results) == 21
    assert len(gates) == 3
    assert all(gate.status == "pass" for gate in gates)
    selected = [item for item in results if item.role == "Selected text on selected row"]
    focus = [item for item in results if item.role == "Focus indicator on canvas"]
    assert len(selected) == 3 and all(item.ratio >= 4.5 for item in selected)
    assert len(focus) == 3 and all(item.ratio >= 3.0 for item in focus)


def test_phase59_tampered_theme_or_missing_token_blocks_certification(tmp_path: Path) -> None:
    service = UxAccessibilityCertificationService(_runtime(tmp_path))
    themes = _themes()
    themes["Light"]["selected_text"] = themes["Light"]["selected_row"]
    themes["Graphite"].pop("focus")
    results, gates = service.audit_theme_tokens(themes)
    light = next(gate for gate in gates if gate.gate_id == "theme-light-contrast")
    graphite = next(gate for gate in gates if gate.gate_id == "theme-graphite-tokens")
    assert light.status == "block"
    assert graphite.status == "block"
    assert any(item.theme == "Light" and item.status == "block" for item in results)


def test_phase59_widget_audit_catches_icon_names_focus_and_target_size(tmp_path: Path) -> None:
    service = UxAccessibilityCertificationService(_runtime(tmp_path))
    issues = service.audit_widget_records(
        (
            {
                "widget_path": "toolbar/more",
                "widget_type": "QToolButton",
                "role": "toolbutton",
                "visible": True,
                "enabled": True,
                "icon_only": True,
                "focusable": False,
                "primary": True,
                "width": 24,
                "height": 24,
            },
            {
                "widget_path": "toolbar/start",
                "widget_type": "QPushButton",
                "role": "button",
                "visible": True,
                "enabled": True,
                "text": "Start",
                "accessible_name": "Start generation",
                "focusable": True,
                "width": 100,
                "height": 34,
                "primary": True,
            },
        )
    )
    categories = {issue.category for issue in issues}
    assert {"accessible-name", "keyboard", "target-size"}.issubset(categories)
    assert any(issue.severity == "blocker" for issue in issues)
    assert not any(issue.widget_path == "toolbar/start" for issue in issues)


def test_phase59_shortcut_conflicts_and_focus_regions_are_deterministic(tmp_path: Path) -> None:
    service = UxAccessibilityCertificationService(_runtime(tmp_path))
    shortcuts = (
        {"label": "Command A", "shortcut": "Ctrl+K", "enabled": True},
        {"label": "Command B", "shortcut": "Ctrl+K", "enabled": True},
        {"label": "Disabled alias", "shortcut": "Ctrl+K", "enabled": False},
    )
    issues = service.audit_shortcuts(shortcuts)
    assert len(issues) == 1
    assert "Command A" in issues[0].detail and "Command B" in issues[0].detail
    snapshot = service.certification_snapshot(
        themes=_themes(),
        active_theme="Dark",
        preference_summary="Standard contrast · Text 100% · Standard focus · Reduced motion · Status announcements on",
        shortcuts=shortcuts,
        focus_regions=("provider", "queue"),
    )
    focus_gate = next(gate for gate in snapshot.gates if gate.gate_id == "keyboard-regions")
    assert focus_gate.status == "block"
    assert "inspector" in focus_gate.detail


def test_phase59_exports_are_structured_and_exclude_private_data(tmp_path: Path) -> None:
    service = UxAccessibilityCertificationService(_runtime(tmp_path))
    snapshot = service.certification_snapshot(
        themes=_themes(),
        active_theme="Dark",
        preference_summary="token=private-value · Reduced motion · Status announcements on",
        widget_records=(
            {
                "widget_path": "api_key=sk-private/widget",
                "widget_type": "QPushButton",
                "role": "button",
                "text": "Authorization: Bearer very-private-token",
                "accessible_name": "Safe button",
                "focusable": True,
                "visible": True,
                "enabled": True,
                "width": 90,
                "height": 34,
            },
        ),
        focus_regions=service.CORE_REGIONS,
    )
    json_path, csv_path = service.export_snapshot(snapshot)
    content = json_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "private-value" not in content
    assert "very-private-token" not in content
    assert "sk-private" not in content
    assert (service.export_dir / "latest.json").exists()


def test_phase59_certified_preset_and_display_profiles(tmp_path: Path) -> None:
    from app.gui.interface_preferences import ContrastMode, FocusStyle, InterfacePreferences

    service = UxAccessibilityCertificationService(_runtime(tmp_path))
    preset = service.recommended_preferences(InterfacePreferences.defaults())
    assert preset.contrast is ContrastMode.HIGH
    assert preset.focus_style is FocusStyle.ENHANCED
    assert preset.text_scale >= 110
    assert preset.reduce_motion and preset.announce_status
    profiles = service.display_profiles()
    assert [profile.scale_percent for profile in profiles] == [100, 125, 150, 200]
    assert all(profile.status == "pass" for profile in profiles)


def test_phase59_cli_script_theme_and_privacy_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    service = (root / "app" / "services" / "ux_accessibility_certification_service.py").read_text(encoding="utf-8")
    theme = (root / "app" / "gui" / "theme.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "ux-certification.ps1").read_text(encoding="utf-8")
    release_check = (root / "scripts" / "release-check.ps1").read_text(encoding="utf-8-sig")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    assert "--ux-certification" in frozen
    assert "--ux-certification-export" in frozen
    assert "project text, filenames, API profiles" in service
    assert "_PHASE59_CERTIFICATION_STYLE" in theme
    assert "QMenu::item:selected" in theme
    assert "Invoke-Expression" not in script
    assert "--ux-certification-export" in release_check
    assert "UX & Accessibility Certification" in main
    assert "Reports: UX & Accessibility Certification" in main


def test_phase59_dialog_mainwindow_and_container_contracts(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container
    from app.gui.dialogs.ux_accessibility_certification_dialog import (
        UxAccessibilityCertificationDialog,
    )
    from app.gui.main import MainWindow

    runtime = _runtime(tmp_path)
    container = create_service_container(runtime)
    service = container.ux_accessibility_certification_service
    dialog = UxAccessibilityCertificationDialog(
        service,
        themes_provider=_themes,
        active_theme_provider=lambda: "Dark",
        preference_summary_provider=lambda: "Reduced motion · Status announcements on",
        focus_regions_provider=lambda: service.CORE_REGIONS,
    )
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "uxAccessibilityCertificationDialog"
    assert dialog.gate_table.rowCount() >= 6
    assert dialog.contrast_table.rowCount() == 21
    exported = dialog.export_snapshot()
    assert exported and all(path.exists() for path in exported)
    dialog.close()

    window = MainWindow(create_application_context(container))
    window.show()
    qt_app.processEvents()
    assert window.accessibleName() == "S Talking AI Audio Studio"
    assert window.table.accessibleName() == "Generation queue"
    assert "UX & Accessibility Certification" in window.actions_by_name
    assert any(
        command.name == "Reports: UX & Accessibility Certification"
        for command in window.command_palette_commands()
    )
    opened = window.open_ux_accessibility_certification()
    assert opened.objectName() == "uxAccessibilityCertificationDialog"
    window.close()
