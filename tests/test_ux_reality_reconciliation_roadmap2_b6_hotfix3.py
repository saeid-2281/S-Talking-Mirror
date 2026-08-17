from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QFormLayout, QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog
from app.gui.icons import icon
from app.gui.main import MainWindow
from app.gui.runtime_font_support import ensure_readable_runtime_font
from app.gui.theme_accessibility_v2 import ux_reality_reconciliation_stylesheet
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for
from app.gui.widgets.application_shell import ProjectPathNotice
from app.models import AppSettings


ROOT = Path(__file__).resolve().parents[1]


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_b6h3_project_path_notice_is_non_modal_and_actionable(qt_app) -> None:  # noqa: ANN001
    host = QWidget()
    notice = ProjectPathNotice(host)
    notice.show_validation(
        ["CSV file is missing", "Output folder is missing"],
        missing_csv=True,
        missing_output=True,
    )

    assert not notice.isWindow()
    assert not notice.isHidden()
    assert not notice.locate_source_button.isHidden()
    assert not notice.choose_output_button.isHidden()
    assert "CSV file is missing" in notice.message.text()

    notice.dismiss_button.click()
    assert notice.isHidden()
    notice.clear()
    assert notice.isHidden()
    host.close()


def test_b6h3_mainwindow_defers_session_restore_until_event_loop() -> None:
    constructor = inspect.getsource(MainWindow.__init__)
    deferred = inspect.getsource(MainWindow._finish_deferred_startup)

    assert "QTimer.singleShot(50,self._finish_deferred_startup)" in constructor
    assert "self.restore_previous_session()" not in constructor
    assert "self.run_startup_recovery()" in deferred
    assert "self.restore_previous_session()" in deferred
    assert "QTimer.singleShot(0,self.refresh_provider_intelligence)" in deferred
    assert "QTimer.singleShot(0,self.refresh_smart_provider_routing)" in deferred


def test_b6h3_missing_project_paths_never_use_modal_warning() -> None:
    source = inspect.getsource(MainWindow.show_path_warnings)

    assert "project_path_notice.show_validation" in source
    assert "notifications.warning" not in source
    assert "statusBar().showMessage" in source


def test_b6h3_missing_project_paths_render_recovery_banner(qt_app, tmp_path: Path) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    missing_csv = tmp_path / "moved" / "lesson.csv"
    missing_output = tmp_path / "moved" / "output"
    window.project_controller.new_project(
        "Moved project",
        missing_csv,
        missing_output,
        AppSettings(provider="mock"),
    )

    validation = window.show_path_warnings()
    qt_app.processEvents()

    assert validation.missing_csv
    assert validation.missing_output
    assert not window.project_path_notice.isHidden()
    assert not window.project_path_notice.locate_source_button.isHidden()
    assert not window.project_path_notice.choose_output_button.isHidden()
    assert "CSV file is missing" in window.project_path_notice.message.text()
    window.close()


def test_b6h3_mainwindow_installs_path_notice_and_hidpi_toolbar(qt_app, tmp_path: Path) -> None:  # noqa: ANN001
    window = _window(tmp_path)

    assert window.application_shell.notice is window.project_path_notice
    assert window.main_toolbar.iconSize() == QSize(24, 24)
    assert window.main_toolbar.minimumHeight() >= 38
    assert window.main_toolbar.maximumHeight() >= window.main_toolbar.minimumHeight()
    window.close()


def test_b6h3_provider_account_details_are_scrollable_and_actions_are_separate(
    qt_app,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    container.api_profile_service.create_profile(
        "Production",
        provider="elevenlabs",
        api_key="test-key",
        active=True,
    )
    dialog = ProviderAccountsDialog(
        container.api_profile_service,
        container.voice_service,
        lambda: AppSettings(provider="elevenlabs"),
        provider_catalog_service=container.provider_catalog_service,
        accounts_center_service=container.provider_accounts_center_service,
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.details_panel.minimumWidth() >= 340
    assert dialog.details_panel.maximumWidth() >= 440
    assert dialog.details_scroll.widgetResizable()
    assert dialog.details_scroll.widget() is dialog.details_content
    assert dialog.details_scroll.horizontalScrollBarPolicy().name == "ScrollBarAlwaysOff"
    assert dialog.details_panel.layout().indexOf(dialog.details_scroll) >= 0
    assert dialog.details_panel.layout().indexOf(dialog.details_actions_host) > dialog.details_panel.layout().indexOf(dialog.details_scroll)
    assert dialog.details_actions_host.layout().count() == 4
    assert dialog.details_form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows
    assert dialog.table.minimumWidth() == 560
    dialog.close()


def test_b6h3_provider_action_grid_keeps_four_controls_in_two_columns(
    qt_app,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    dialog = ProviderAccountsDialog(
        container.api_profile_service,
        container.voice_service,
        lambda: AppSettings(provider="elevenlabs"),
        provider_catalog_service=container.provider_catalog_service,
        accounts_center_service=container.provider_accounts_center_service,
    )
    layout = dialog.details_actions_host.layout()

    positions = {
        (layout.getItemPosition(index)[0], layout.getItemPosition(index)[1])
        for index in range(layout.count())
    }
    assert positions == {(0, 0), (0, 1), (1, 0), (1, 1)}
    dialog.close()


def test_b6h3_icon_pipeline_renders_for_device_pixel_ratio(qt_app) -> None:  # noqa: ANN001
    source = (ROOT / "app" / "gui" / "icons.py").read_text(encoding="utf-8")
    generated = icon("settings", size=24)

    assert not generated.isNull()
    assert "devicePixelRatio()" in source
    assert "physical_size" in source
    assert "pixmap.setDevicePixelRatio(device_ratio)" in source


def test_b6h3_menu_and_toolbar_states_do_not_change_geometry() -> None:
    stylesheet = ux_reality_reconciliation_stylesheet(is_dark=True)

    assert "Roadmap 2 B6 Hotfix 3" in stylesheet
    assert "QMenuBar::item" in stylesheet
    assert "border:1px solid transparent" in stylesheet
    assert "QMenuBar::item:selected" in stylesheet
    assert "QMenuBar::item:focus" in stylesheet
    assert "QToolBar#mainToolbar" in stylesheet


def test_b6h3_manual_dark_review_hosts_are_neutral_soft_professional_surfaces() -> None:
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    stylesheet = ux_reality_reconciliation_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )

    for selector in (
        "QFrame#queueInspectorHeader",
        "QFrame#queueInspectorCard",
        "QFrame#queueInspectorActions",
        "QFrame#providerAccountDetails",
        "QFrame#providerAccountIdentity",
        "QFrame#providerAccountMetadataCard",
        "QPlainTextEdit#queueDetailsText",
    ):
        assert selector in stylesheet

    assert f"background:{semantic.surface}" in stylesheet
    assert f"background:{semantic.surface_secondary}" in stylesheet


def test_b6h3_system_light_dark_remain_palette_driven() -> None:
    assert ACTIVE_CONCEPT == "soft_professional"
    light = ux_reality_reconciliation_stylesheet(is_dark=False)
    dark = ux_reality_reconciliation_stylesheet(is_dark=True)

    assert "Roadmap 2 B6 Hotfix 3" in light
    assert "Roadmap 2 B6 Hotfix 3" in dark
    assert palette_for(is_dark=False).surface in light
    assert palette_for(is_dark=True).surface in dark


def test_b6h3_runtime_font_support_prevents_silent_square_glyph_certification(qt_app) -> None:  # noqa: ANN001
    usable, family = ensure_readable_runtime_font(qt_app)

    assert usable
    assert family
    source = (
        ROOT / "scripts" / "certify_ux_reconciliation_roadmap2_b6_hotfix3.py"
    ).read_text(encoding="utf-8")
    assert "require_explicit_font=True" in source
    assert "latin_danish_glyphs_available" in source
    assert "ÆØÅæøå" in source


def test_b6h3_historical_theme_certifiers_now_require_readable_font() -> None:
    for relative in (
        "scripts/certify_dark_theme_completion_roadmap2_b6_hotfix2.py",
        "scripts/certify_three_theme_surface_coherence_roadmap2_a121.py",
        "scripts/certify_product_ux_visual_roadmap2_a12.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "ensure_readable_runtime_font" in source
        assert "require_explicit_font=True" in source


def test_b6h3_portable_profile_and_secret_storage_are_separate() -> None:
    runtime_source = (ROOT / "app" / "config" / "runtime.py").read_text(encoding="utf-8")
    container_source = (ROOT / "app" / "container.py").read_text(encoding="utf-8")
    credential_source = (
        ROOT / "app" / "services" / "secure_credentials.py"
    ).read_text(encoding="utf-8")

    assert 'writable_root = exe_dir / "S-Talking-Data"' in runtime_source
    assert 'settings_dir = writable_root / "settings"' in runtime_source
    assert 'ApiProfileService(settings_dir / "api-profiles.json"' in container_source
    assert 'SecureCredentialStore(settings_dir / "credentials")' in container_source
    assert "windows-credential-manager" in credential_source
    assert "legacy = self._read_file_secret(key)" in credential_source
    assert "self._native_backend.set_password(self._target(key), legacy)" in credential_source


def test_b6h3_scope_does_not_change_generation_or_database_authority(tmp_path: Path) -> None:
    presentation = inspect.getsource(ProjectPathNotice) + inspect.getsource(
        ensure_readable_runtime_font
    ) + ux_reality_reconciliation_stylesheet(is_dark=True)
    for forbidden in (
        "generation_controller.start(",
        "run_preflight(",
        "activate_failover_target(",
        "provider.setCurrentText(",
    ):
        assert forbidden not in presentation

    from app.database.connection import Database

    assert Database(tmp_path / "schema.db").expected_schema_version == 23
