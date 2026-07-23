from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.bootstrap import ApplicationContext, create_application_context
from app.controllers import GenerationController, ProjectController, SettingsController
from app.gui.notifications import NotificationService
from app.models import AppSettings
from app.models.domain import TTSJob
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


def test_application_bootstrap_constructs_dependencies() -> None:
    context = create_application_context()

    assert isinstance(context.project_controller, ProjectController)
    assert isinstance(context.generation_controller, GenerationController)
    assert isinstance(context.settings_controller, SettingsController)


def test_main_window_accepts_injected_dependencies(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(context(tmp_path))

    assert isinstance(window.project_controller, ProjectController)


def test_gui_import_does_not_initialize_database_as_import_side_effect(monkeypatch) -> None:
    import app.database

    calls = []
    monkeypatch.setattr(app.database, "initialize_default_database", lambda: calls.append(True))
    import app.gui.main  # noqa: F401

    assert calls == []


def test_project_controller_delegates_to_project_manager(tmp_path: Path) -> None:
    service = manager(tmp_path)
    controller = ProjectController(service)

    state = controller.new_project("Lesson", None, None, AppSettings(provider="elevenlabs"))

    assert state.provider == "mock"
    assert service.current_project is state


def test_settings_controller_suppresses_dirty_state_during_programmatic_load() -> None:
    controller = SettingsController()

    with controller.loading():
        changed = controller.settings_changed(AppSettings(provider="mock"))

    assert changed is False


def test_settings_changes_mark_open_project_dirty(tmp_path: Path) -> None:
    service = manager(tmp_path)
    project = ProjectController(service)
    settings = SettingsController()
    project.new_project("Lesson", None, None, AppSettings(provider="mock"))
    settings.settings_changed(AppSettings(provider="mock"))

    if settings.settings_changed(AppSettings(provider="piper")):
        project.update_settings(AppSettings(provider="piper"))

    assert project.current_project.dirty is True
    assert project.current_project.provider == "piper"


def test_generation_controller_starts_mock_generation(qt_app, tmp_path: Path) -> None:
    controller = GenerationController(database_path=tmp_path / "legacy.db")
    settings = AppSettings(provider="mock", delay_seconds=0)
    jobs = [TTSJob(row_number=2, filename="001.wav", text="Hej")]
    parent = qt_app

    assert controller.start(parent, jobs, settings, tmp_path, "project-key") is True
    wait_until_inactive(qt_app, controller)

    assert (tmp_path / "001.wav").exists()
    assert controller.is_active is False


def test_generation_controller_pause_resume_stop_delegate() -> None:
    controller = GenerationController()
    worker = FakeWorker()
    controller.worker = worker

    assert controller.pause() is True
    assert controller.resume() is True
    assert controller.stop() is True
    assert worker.calls == ["pause", "resume", "stop"]


def test_generation_active_state_is_accurate() -> None:
    controller = GenerationController()

    assert controller.is_active is False
    controller.worker = FakeWorker()
    assert controller.is_active is True


def test_controllers_do_not_import_qmessagebox() -> None:
    controller_sources = [
        Path("app/controllers/project_controller.py").read_text(encoding="utf-8"),
        Path("app/controllers/generation_controller.py").read_text(encoding="utf-8"),
        Path("app/controllers/settings_controller.py").read_text(encoding="utf-8"),
    ]

    assert all("QMessageBox" not in source for source in controller_sources)


def test_main_window_does_not_instantiate_project_manager_or_generation_worker() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")

    assert "ProjectManager(" not in source
    assert "GenerationWorker(" not in source
    assert "QThread(" not in source


def test_project_menu_actions_exist(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(context(tmp_path))
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

    window = MainWindow(context(tmp_path))
    window.project_controller.new_project("Danish Lessons", None, None, AppSettings(provider="mock"))
    window.update_window_title()

    assert window.windowTitle() == "S Talking — Danish Lessons *"


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


def context(tmp_path: Path) -> ApplicationContext:
    return ApplicationContext(
        project_controller=ProjectController(manager(tmp_path)),
        generation_controller=GenerationController(database_path=tmp_path / "legacy.db"),
        settings_controller=SettingsController(tmp_path / "settings.json"),
        notification_service=FakeNotifications(),
    )


def wait_until_inactive(qt_app, controller: GenerationController) -> None:
    deadline = time.time() + 5
    while controller.is_active and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    qt_app.processEvents()


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def stop(self) -> None:
        self.calls.append("stop")


@dataclass
class FakeNotifications(NotificationService):
    parent: object | None = None

    def information(self, title: str, message: str) -> None:
        pass

    def warning(self, title: str, message: str) -> None:
        pass

    def error(self, title: str, message: str) -> None:
        pass

    def confirmation(self, title: str, message: str) -> bool:
        return True
