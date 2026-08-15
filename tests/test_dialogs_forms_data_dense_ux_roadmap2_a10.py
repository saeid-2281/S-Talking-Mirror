from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QTableView,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialog_form_modernization import (
    DATA_DENSE_SURFACES,
    DIALOG_SURFACE_INVENTORY,
    DialogFormModernizer,
    dialog_form_stylesheet,
)
from app.gui.main import MainWindow
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


BASELINE_A91 = "052812d2e8be109e4150519e5460efc61551eccb"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    container = create_service_container(runtime)
    return MainWindow(create_application_context(container))


def test_a10_uses_soft_professional_tokens_without_taking_mainwindow_palette_authority() -> None:
    assert ACTIVE_CONCEPT == "soft_professional"
    light = palette_for(is_dark=False)
    assert light.canvas == "#F7F6F3"
    assert light.surface == "#FFFFFF"
    assert light.primary == "#5271C6"

    stylesheet = dialog_form_stylesheet(is_dark=False)
    assert "Roadmap 2 A10" in stylesheet
    assert 'QDialog[a10Modernized="true"]' in stylesheet
    assert "QMainWindow" not in stylesheet
    assert "background:#F7F6F3" in stylesheet


def test_a10_mainwindow_installs_dialog_modernizer_and_appends_theme_overlay() -> None:
    build_source = inspect.getsource(MainWindow.build)
    theme_source = inspect.getsource(MainWindow.apply_theme)
    density_source = inspect.getsource(MainWindow.apply_density)

    assert "DialogFormModernizer(self)" in build_source
    assert "dialog_form_modernizer.install()" in build_source
    assert "dialog_form_stylesheet" in theme_source
    assert "dialog_form_modernizer.apply_density" in density_source


def test_a10_product_inventory_and_modernizer_remain_presentation_only() -> None:
    assert {
        "ProviderAccountsDialog",
        "ProviderSetupWizardDialog",
        "UnifiedVoiceModelCatalogDialog",
        "PreflightDialog",
        "PronunciationReviewDialog",
        "SourceImportReviewDialog",
        "InterfacePreferencesDialog",
    }.issubset(set(DIALOG_SURFACE_INVENTORY))
    assert {"tables", "trees", "lists", "catalogs", "review grids"}.issubset(
        set(DATA_DENSE_SURFACES)
    )

    source = inspect.getsource(DialogFormModernizer)
    forbidden = (
        "run_preflight(",
        "start_generation(",
        "generation_controller.start(",
        "provider.setCurrent",
        "model.setCurrent",
        "voice.setText",
        "language.setCurrent",
        "apply_smart_provider_routing_recommendation(",
        "detect_language(",
        "save_project(",
    )
    for token in forbidden:
        assert token not in source
    polish_source = inspect.getsource(DialogFormModernizer.polish_dialog)
    assert polish_source.index("_repolish(dialog)") < polish_source.index(
        "_enforce_control_geometry(dialog)"
    )


def test_a10_runtime_marks_dialog_and_applies_calm_root_geometry(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(4)
    layout.addWidget(QLabel("A10 dialog"))

    dialog.show()
    qt_app.processEvents()

    assert dialog.property("a10Modernized") is True
    assert dialog.property("visualAlignment") == "soft-professional"
    margins = layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (16, 14, 16, 16)
    assert layout.spacing() >= 10
    dialog.close()
    window.close()


def test_a10_form_layout_has_readable_spacing_growth_and_label_semantics(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    form = QFormLayout(dialog)
    label = QLabel("Profile")
    field = QLineEdit()
    label.setBuddy(field)
    form.addRow(label, field)

    dialog.show()
    qt_app.processEvents()

    assert form.horizontalSpacing() >= 12
    assert form.verticalSpacing() >= 8
    assert form.fieldGrowthPolicy() == QFormLayout.AllNonFixedFieldsGrow
    assert label.property("visualRole") == "formLabel"
    assert field.property("visualRole") == "formControl"
    assert field.minimumHeight() >= 34
    dialog.close()
    window.close()


def test_a10_data_dense_views_get_semantic_role_without_edit_behavior_mutation(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    table = QTableView()
    tree = QTreeView()
    listing = QListView()
    original_edit_triggers = table.editTriggers()
    for view in (table, tree, listing):
        layout.addWidget(view)

    dialog.show()
    qt_app.processEvents()

    for view in (table, tree, listing):
        assert view.property("visualRole") == "dataDense"
        assert view.alternatingRowColors() is True
    assert table.editTriggers() == original_edit_triggers
    dialog.close()
    window.close()


def test_a10_dialog_button_box_actions_gain_consistent_control_geometry(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    layout.addWidget(buttons)

    dialog.show()
    qt_app.processEvents()

    assert buttons.property("visualRole") == "dialogActions"
    for button in buttons.buttons():
        assert button.property("visualRole") == "dialogAction"
        assert button.minimumHeight() >= 34
        if button.text().strip():
            assert button.minimumWidth() >= 84
    dialog.close()
    window.close()


def test_a10_tabs_scroll_and_multiline_controls_are_classified(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "General")
    scroll = QScrollArea()
    plain = QPlainTextEdit()
    rich = QTextEdit()
    layout.addWidget(tabs)
    layout.addWidget(scroll)
    layout.addWidget(plain)
    layout.addWidget(rich)

    dialog.show()
    qt_app.processEvents()

    assert tabs.property("visualRole") == "dialogTabs"
    assert tabs.documentMode() is True
    assert scroll.property("visualRole") == "dialogScroll"
    assert plain.property("visualRole") == "multilineFormControl"
    assert rich.property("visualRole") == "multilineFormControl"
    dialog.close()
    window.close()


def test_a10_density_refresh_reapplies_open_dialog_control_height(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    field = QLineEdit()
    layout.addWidget(field)
    dialog.show()
    qt_app.processEvents()

    window.apply_density("Comfortable")
    qt_app.processEvents()
    assert field.property("visualRole") == "formControl"
    assert field.minimumHeight() >= 38
    dialog.close()
    window.close()


def test_a10_leaves_native_system_dialog_classes_outside_custom_modernization(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    file_dialog = QFileDialog(window)
    font_dialog = QFontDialog(window)

    assert DialogFormModernizer._is_native_system_dialog(file_dialog) is True
    assert DialogFormModernizer._is_native_system_dialog(font_dialog) is True
    assert file_dialog.property("a10Modernized") is None
    assert font_dialog.property("a10Modernized") is None
    window.close()
