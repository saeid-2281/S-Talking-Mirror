from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.models import AppSettings
from app.services.project_manager import ProjectManager


def manager(tmp_path: Path) -> ProjectManager:
    return ProjectManager(tmp_path / "projects.sqlite3")


def test_create_new_project(tmp_path: Path) -> None:
    service = manager(tmp_path)
    csv_path = tmp_path / "input.csv"
    output_path = tmp_path / "output"
    state = service.new_project("Danish Lessons", csv_path, output_path)

    assert state.project_id is not None
    assert state.name == "Danish Lessons"
    assert state.provider == "mock"
    assert state.dirty is True
    assert state.project_file is None


def test_save_and_reopen_project(tmp_path: Path) -> None:
    service = manager(tmp_path)
    path = tmp_path / "lesson.stproj"
    service.new_project("Lesson", provider="mock")
    saved = service.save_project_as(path)

    reopened = manager(tmp_path).open_project(path)

    assert saved.dirty is False
    assert reopened.name == "Lesson"
    assert reopened.provider == "mock"
    assert reopened.project_file == path


def test_save_as_preserves_project_id(tmp_path: Path) -> None:
    service = manager(tmp_path)
    state = service.new_project("Lesson")
    project_id = state.project_id

    saved = service.save_project_as(tmp_path / "copy.stproj")

    assert saved.project_id == project_id


def test_dirty_flag_lifecycle(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson")
    service.save_project_as(tmp_path / "lesson.stproj")

    assert service.current_project.dirty is False
    service.mark_dirty()
    assert service.current_project.dirty is True
    service.save_project()
    assert service.current_project.dirty is False


def test_atomic_save_writes_valid_utf8_json(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Åge går på arbejde")
    path = tmp_path / "unicode.stproj"

    service.save_project_as(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["name"] == "Åge går på arbejde"
    assert not list(tmp_path.glob(".*.tmp"))


def test_malformed_project_handling(tmp_path: Path) -> None:
    path = tmp_path / "bad.stproj"
    path.write_text("{nope", encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed project file"):
        manager(tmp_path).open_project(path)


def test_legacy_project_compatibility(tmp_path: Path) -> None:
    path = tmp_path / "legacy.stproj"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Legacy",
                "csv_path": "missing.csv",
                "output_path": "missing-output",
                "settings": AppSettings(provider="mock").model_dump(),
            }
        ),
        encoding="utf-8",
    )

    state = manager(tmp_path).open_project(path)

    assert state.name == "Legacy"
    assert state.provider == "mock"


def test_missing_csv_output_path_validation(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson", tmp_path / "missing.csv", tmp_path / "missing-output")

    validation = service.validate_current_paths()

    assert validation.missing_csv is True
    assert validation.missing_output is True


def test_recent_project_ordering(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("First")
    first = service.save_project_as(tmp_path / "first.stproj")
    service.new_project("Second")
    second = service.save_project_as(tmp_path / "second.stproj")

    recent = service.list_recent_projects()

    assert [project.id for project in recent[:2]] == [second.project_id, first.project_id]


def test_remove_recent_project_entry(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson")
    saved = service.save_project_as(tmp_path / "lesson.stproj")

    service.remove_recent_project(saved.project_id)

    assert service.list_recent_projects() == []


def test_autosave_skips_clean_project(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson")
    path = tmp_path / "lesson.stproj"
    service.save_project_as(path)
    before = path.stat().st_mtime_ns

    assert service.autosave_if_needed() is False
    assert path.stat().st_mtime_ns == before


def test_autosave_skips_project_without_project_file(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson")

    assert service.autosave_if_needed() is False


def test_autosave_saves_dirty_project(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson")
    path = tmp_path / "lesson.stproj"
    service.save_project_as(path)
    service.update_provider("piper")

    assert service.autosave_if_needed() is True
    assert json.loads(path.read_text(encoding="utf-8"))["provider"] == "piper"


def test_autosave_skips_while_generation_active(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Lesson")
    service.save_project_as(tmp_path / "lesson.stproj")
    service.mark_dirty()

    assert service.autosave_if_needed(generation_active=True) is False
    assert service.current_project.dirty is True


def test_gui_main_window_imports_successfully() -> None:
    import app.gui.main  # noqa: F401


def test_project_menu_actions_exist(qt_app) -> None:
    from app.gui.main import MainWindow

    window = MainWindow()
    actions = [
        action.text()
        for action in window.menuBar().actions()[0].menu().actions()
    ]

    assert actions == [
        "New Project",
        "Open Project",
        "Save",
        "Save As",
        "Recent Projects",
        "Close Project",
        "Exit",
    ]


def test_window_title_updates_with_dirty_marker(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow()
    window.project_manager = manager(tmp_path)
    window.project_manager.new_project("Danish Lessons")
    window.update_window_title()

    assert window.windowTitle() == "S Talking — Danish Lessons *"


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app
