from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QToolButton

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.theme import STATUS_COLORS, ThemeManager
from app.models import AppSettings, JobStatus, TTSJob


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path):
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    return MainWindow(context)


def test_preflight_warning_status_allows_continue(tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    out = tmp_path / "out"
    out.mkdir()
    (out / "one.wav").write_bytes(b"existing")

    state = context.preflight_service.run(
        jobs=[TTSJob(row_number=2, filename="one.wav", text="Hej")],
        settings=AppSettings(provider="mock", skip_existing=True),
        output_dir=out,
    )

    assert state.status == "Ready with warnings"
    assert state.can_start is True


def test_row_range_filters_queue_metrics_and_generation(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    jobs = [TTSJob(row_number=i, filename=f"{i}.wav", text="Hej") for i in range(1, 6)]
    window.generation_controller.set_jobs(jobs)

    window.range_from.setValue(2)
    window.range_to.setValue(4)

    assert [job.row_number for job in window.generation_controller.range_jobs()] == [2, 3, 4]
    assert window.generation_controller.metrics().total == 3
    assert "3 jobs" in window.range_summary_label.text()
    window.close()


def test_model_dropdown_restore_defaults_and_theme_switch(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert isinstance(window.model, QComboBox)
    window.set_model_value("custom-model")
    window.apply_theme("Light")
    window.restore_defaults()

    assert window.provider.currentText() == "mock"
    assert window.current_model_id() == "eleven_multilingual_v2"
    assert window.key.text() == ""
    assert ThemeManager().current() == "Dark"
    window.close()


def test_queue_toolbar_grouped_actions_and_context_menu_methods(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    jobs = [TTSJob(row_number=1, filename="one.wav", text="Hej", status=JobStatus.FAILED)]
    window.generation_controller.set_jobs(jobs)
    window.render_queue()
    window.table.selectRow(0)

    assert isinstance(window.retry_menu_button, QToolButton)
    assert window.retry_menu_button.menu().actions()
    window.copy_selected_filename()
    assert QApplication.clipboard().text() == "one.wav"
    window.copy_selected_text()
    assert QApplication.clipboard().text() == "Hej"
    assert hasattr(window, "generate_selected_row")
    assert hasattr(window, "generate_selected_rows")
    window.close()


def test_status_palette_consistent() -> None:
    assert STATUS_COLORS["pending"] == "#60A5FA"
    assert STATUS_COLORS["running"] == "#F59E0B"
    assert STATUS_COLORS["completed"] == "#22C55E"
    assert STATUS_COLORS["failed"] == "#EF4444"
    assert STATUS_COLORS["skipped"] == "#94A3B8"
