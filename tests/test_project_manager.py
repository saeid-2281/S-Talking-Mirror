from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from app.bootstrap import ApplicationContext, create_application_context
from app.config.runtime import RuntimeConfig
from app.container import ServiceContainer, create_service_container
from app.controllers import GenerationController, ProjectController, SettingsController
from app.controllers.project_controller import sanitize_project_filename
from app.gui.notifications import QtNotificationService
from app.gui.notifications import NotificationService
from app.models import AppSettings
from app.models.domain import TTSJob
from app.services.project_manager import ProjectManager


def manager(tmp_path: Path) -> ProjectManager:
    return create_service_container(RuntimeConfig.from_root(tmp_path)).project_manager


def project_controller(tmp_path: Path) -> ProjectController:
    return create_service_container(RuntimeConfig.from_root(tmp_path)).project_controller


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


def test_save_as_suggested_filename_uses_project_name(tmp_path: Path) -> None:
    controller = project_controller(tmp_path)
    controller.new_project("Danish Alphabet", None, None, AppSettings(provider="mock"))

    assert controller.suggested_save_as_path() == tmp_path / "Danish Alphabet.stproj"


def test_invalid_windows_filename_characters_are_sanitized() -> None:
    assert sanitize_project_filename('A<>:"/\\|?*B') == "A_________B.stproj"


def test_unicode_project_names_remain_usable() -> None:
    assert sanitize_project_filename("Dansk Åge فارسی") == "Dansk Åge فارسی.stproj"


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


def test_api_key_is_not_written_to_project_file(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.new_project("Secret", settings=AppSettings(provider="elevenlabs", api_key="SECRET"))
    path = tmp_path / "secret.stproj"

    service.save_project_as(path)

    assert "SECRET" not in path.read_text(encoding="utf-8")


def test_project_loading_combines_configuration_with_secure_global_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        AppSettings(provider="elevenlabs", api_key="GLOBAL").model_dump_json(),
        encoding="utf-8",
    )
    controller = create_service_container(RuntimeConfig.from_root(tmp_path)).project_controller
    project_path = tmp_path / "project.stproj"
    project_path.write_text(
        json.dumps(
            {
                "name": "Project",
                "settings": AppSettings(
                    provider="elevenlabs",
                    api_key="",
                    voice_id="voice-project",
                ).model_dump(),
            }
        ),
        encoding="utf-8",
    )

    state = controller.open_project(project_path)

    assert state.settings.voice_id == "voice-project"
    assert state.settings.api_key == "GLOBAL"


def test_global_defaults_are_not_modified_by_project_setting_changes(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    container.settings_controller.save_global_settings(AppSettings(provider="mock"))
    container.project_controller.new_project("Project", None, None, AppSettings(provider="mock"))

    container.project_controller.update_settings(AppSettings(provider="piper"))

    assert container.settings_controller.load_global_settings().provider == "mock"


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

    assert isinstance(context.container, ServiceContainer)
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
    controller = ProjectController(service, RuntimeConfig.from_root(tmp_path))

    state = controller.new_project("Lesson", None, None, AppSettings(provider="elevenlabs"))

    assert state.provider == "elevenlabs"
    assert service.current_project is state


def test_settings_controller_suppresses_dirty_state_during_programmatic_load() -> None:
    controller = SettingsController(Path("settings.json"))

    with controller.loading():
        changed = controller.settings_changed(AppSettings(provider="mock"))

    assert changed is False


def test_settings_changes_mark_open_project_dirty(tmp_path: Path) -> None:
    service = manager(tmp_path)
    project = ProjectController(service, RuntimeConfig.from_root(tmp_path))
    settings = SettingsController(tmp_path / "settings.json")
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
    controller = GenerationController(Path("legacy.db"))
    worker = FakeWorker()
    controller.worker = worker

    assert controller.pause() is True
    assert controller.resume() is True
    assert controller.stop() is True
    assert worker.calls == ["pause", "resume", "stop"]
    assert controller.is_paused is False


def test_generation_active_state_is_accurate() -> None:
    controller = GenerationController(Path("legacy.db"))

    assert controller.is_active is False
    controller.worker = FakeWorker()
    assert controller.is_active is True


def test_runtime_configuration_resolves_all_paths(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)

    assert runtime.app_root == tmp_path.resolve()
    assert runtime.data_dir == tmp_path / "data"
    assert runtime.database_path == tmp_path / "data" / "s_talking.db"
    assert runtime.legacy_database_path == tmp_path / "data" / "s-talking.db"
    assert runtime.settings_path == tmp_path / "settings.json"
    assert runtime.log_dir == tmp_path / "logs"
    assert runtime.cache_dir == tmp_path / "cache"
    assert runtime.default_output_dir == tmp_path / "output"


def test_bootstrap_creates_required_directories(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)

    create_service_container(runtime)

    assert runtime.data_dir.exists()
    assert runtime.log_dir.exists()
    assert runtime.cache_dir.exists()
    assert runtime.default_output_dir.exists()


def test_service_container_constructs_all_dependencies(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))

    assert container.runtime.database_path == tmp_path / "data" / "s_talking.db"
    assert container.database.path == container.runtime.database_path
    assert isinstance(container.project_controller, ProjectController)
    assert isinstance(container.generation_controller, GenerationController)
    assert isinstance(container.settings_controller, SettingsController)


def test_database_path_is_injected_into_generation_controller(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))

    assert container.generation_controller.database_path == container.runtime.legacy_database_path


def test_settings_path_is_injected_into_settings_controller(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))

    assert container.settings_controller.settings_path == container.runtime.settings_path


def test_generation_controller_owns_jobs() -> None:
    controller = GenerationController(Path("legacy.db"))
    jobs = [TTSJob(row_number=2, filename="001.wav", text="Hej")]

    controller.set_jobs(jobs)

    assert controller.has_jobs() is True
    assert controller.jobs == jobs
    controller.clear_jobs()
    assert controller.has_jobs() is False


def test_generation_controller_owns_paused_state() -> None:
    controller = GenerationController(Path("legacy.db"))
    controller.worker = FakeWorker()

    controller.pause()
    assert controller.is_paused is True
    controller.resume()
    assert controller.is_paused is False


def test_project_controller_returns_project_key(tmp_path: Path) -> None:
    controller = project_controller(tmp_path)
    state = controller.new_project("Lesson", None, None, AppSettings(provider="mock"))

    assert controller.current_project_key == state.project_key


def test_ad_hoc_generation_context_without_open_project(tmp_path: Path) -> None:
    controller = project_controller(tmp_path)

    context = controller.generation_context(tmp_path / "output")

    assert context.project_name == "Untitled project"
    assert context.project_key.startswith("adhoc:")
    assert context.output_path == tmp_path / "output"


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
    assert "ProjectFile" not in source
    assert "self.jobs" not in source
    assert "self.paused" not in source
    assert "data/s-talking.db" not in source
    assert "settings.json" not in source


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


def test_csv_auto_load_after_new_project(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    csv_path = tmp_path / "input.csv"
    csv_path.write_text("filename,text\n001.wav,Hej\n", encoding="utf-8")
    window = MainWindow(context(tmp_path))
    state = window.project_controller.new_project("Project", csv_path, tmp_path / "out", window.settings())
    window.apply_project_state(state)
    window.load_csv(update_project=False)

    assert window.table.rowCount() == 1
    assert len(window.generation_controller.jobs) == 1


def test_csv_auto_load_after_open_project(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    csv_path = tmp_path / "input.csv"
    csv_path.write_text("filename,text\n001.wav,Hej\n", encoding="utf-8")
    service = manager(tmp_path)
    service.new_project("Project", csv_path, tmp_path / "out")
    project_file = tmp_path / "project.stproj"
    service.save_project_as(project_file)
    window = MainWindow(context(tmp_path))
    state = window.project_controller.open_project(project_file)
    window.apply_project_state(state)
    window.load_csv(update_project=False)

    assert window.table.rowCount() == 1


def test_no_duplicate_csv_load(monkeypatch, qt_app, tmp_path: Path) -> None:
    from app.gui import main as gui_main
    from app.gui.main import MainWindow

    csv_path = tmp_path / "input.csv"
    csv_path.write_text("filename,text\n001.wav,Hej\n", encoding="utf-8")
    calls = []
    original = gui_main.load_jobs

    def counted(path: Path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(gui_main, "load_jobs", counted)
    window = MainWindow(context(tmp_path))
    window.csv.setText(str(csv_path))
    window.load_csv(update_project=False)

    assert len(calls) == 1


def test_reload_csv_works(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    csv_path = tmp_path / "input.csv"
    csv_path.write_text("filename,text\n001.wav,Hej\n", encoding="utf-8")
    window = MainWindow(context(tmp_path))
    window.csv.setText(str(csv_path))
    window.reload_csv()

    assert len(window.generation_controller.jobs) == 1


def test_spinbox_steps_and_wheel_guard(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(context(tmp_path))
    assert window.delay.singleStep() == pytest.approx(0.1)
    assert window.retries.singleStep() == 1
    assert window.speed.singleStep() == pytest.approx(0.05)
    delay = window.delay.value()
    window.delay.stepUp()
    assert window.delay.value() == pytest.approx(delay + 0.1)
    window.delay.stepDown()
    assert window.delay.value() == pytest.approx(delay)
    retries = window.retries.value()
    window.retries.stepUp()
    assert window.retries.value() == retries + 1
    speed = window.speed.value()
    window.speed.stepUp()
    assert window.speed.value() == pytest.approx(speed + 0.05)
    window.speed.clearFocus()
    before = window.speed.value()
    wheel = QWheelEvent(
        QPointF(1, 1),
        QPointF(1, 1),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    qt_app.sendEvent(window.speed, wheel)
    assert window.speed.value() == pytest.approx(before)


def test_completion_summary_is_non_modal(qt_app) -> None:
    notifications = QtNotificationService()

    notifications.show_generation_summary({"total": 1, "completed": 1, "skipped": 0, "failed": 0})

    assert notifications.summary_dialogs
    assert notifications.summary_dialogs[0].isModal() is False
    notifications.close_summaries()


def test_main_window_may_close_while_summary_is_visible(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(context(tmp_path))
    window.notifications.show_generation_summary({"total": 1, "completed": 1, "skipped": 0, "failed": 0})
    window.close()

    assert True


def test_separate_projects_retain_separate_tts_settings(tmp_path: Path) -> None:
    service = manager(tmp_path)
    first = service.new_project("First", settings=AppSettings(provider="mock", voice_id="one"))
    first_path = tmp_path / "first.stproj"
    service.save_project_as(first_path)
    second = service.new_project("Second", settings=AppSettings(provider="piper", voice_id="two"))
    second_path = tmp_path / "second.stproj"
    service.save_project_as(second_path)

    first_loaded = service.open_project(first_path)
    second_loaded = service.open_project(second_path)

    assert first.project_id != second.project_id
    assert first_loaded.settings.voice_id == "one"
    assert second_loaded.settings.voice_id == "two"


def test_scripts_exist_and_contain_no_hardcoded_user_paths() -> None:
    for path in [
        Path("scripts/dev-check.ps1"),
        Path("scripts/run.ps1"),
        Path("scripts/new-feature.ps1"),
        Path("scripts/spinbox-demo.py"),
        Path("scripts/prepare-commit.ps1"),
        Path("S-Talking.cmd"),
        Path("S-Talking-Dev.cmd"),
        Path("S-Talking-Diagnostics.cmd"),
        Path(".vscode/tasks.json"),
    ]:
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text
        assert "D:\\Projects" not in text


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
    services = create_service_container(RuntimeConfig.from_root(tmp_path))
    app_context = create_application_context(services)
    app_context.notification_service = FakeNotifications()
    return app_context


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

    def show_generation_summary(self, summary: dict) -> None:
        pass
