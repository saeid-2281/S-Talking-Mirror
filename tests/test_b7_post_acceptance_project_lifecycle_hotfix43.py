from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.models.domain import AppSettings
from app.services.project_manager import ProjectManager


def _manager(tmp_path: Path) -> ProjectManager:
    from app.config.runtime import RuntimeConfig
    from app.container import create_service_container

    return create_service_container(RuntimeConfig.from_root(tmp_path)).project_manager


def test_h43_missing_source_rebases_to_project_folder_and_persists(tmp_path: Path) -> None:
    project_dir = tmp_path / "portable-project"
    old_dir = tmp_path / "old-location"
    project_dir.mkdir()
    source = project_dir / "lesson.csv"
    source.write_text("filename,text\n001.wav,Hej\n", encoding="utf-8")
    project_file = project_dir / "lesson.stproj"
    project_file.write_text(
        json.dumps(
            {
                "name": "Moved lesson",
                "csv_path": str(old_dir / source.name),
                "output_path": str(project_dir / "out"),
                "provider": "mock",
                "settings": AppSettings(provider="mock").model_dump(),
            }
        ),
        encoding="utf-8",
    )

    state = _manager(tmp_path).open_project(project_file)

    assert state.csv_path == source
    persisted = json.loads(project_file.read_text(encoding="utf-8"))
    assert Path(persisted["csv_path"]) == source


def test_h43_missing_source_stays_missing_when_project_folder_has_no_match(tmp_path: Path) -> None:
    project_file = tmp_path / "lesson.stproj"
    missing = tmp_path / "elsewhere" / "lesson.csv"
    project_file.write_text(
        json.dumps(
            {
                "name": "Missing lesson",
                "csv_path": str(missing),
                "provider": "mock",
                "settings": AppSettings(provider="mock").model_dump(),
            }
        ),
        encoding="utf-8",
    )

    state = _manager(tmp_path).open_project(project_file)

    assert state.csv_path == missing
    assert not state.csv_path.exists()


def test_h43_project_manager_relocation_is_filename_scoped() -> None:
    source = inspect.getsource(ProjectManager._relocate_missing_csv_next_to_project)

    assert "project_path.parent / source.name" in source
    assert "candidate.is_file()" in source
    assert "state.csv_path = candidate" in source


def test_h43_generation_controller_keeps_thread_authoritative_until_finished() -> None:
    from app.controllers.generation_controller import GenerationController

    active = inspect.getsource(GenerationController.is_active.fget)
    wait = inspect.getsource(GenerationController.wait_until_idle)
    finished = inspect.getsource(GenerationController._finished)
    failed = inspect.getsource(GenerationController._failed)
    cleanup = inspect.getsource(GenerationController._thread_finished)

    assert "thread.isRunning()" in active
    assert "thread.wait" in wait
    assert "self.thread.quit()" in finished
    assert "self.thread.quit()" in failed
    assert "self.thread = None" in cleanup


def test_h43_mainwindow_uses_one_safe_open_route_for_regular_and_recent_projects() -> None:
    from app.gui.main import MainWindow

    regular = inspect.getsource(MainWindow.open_project)
    recent = inspect.getsource(MainWindow.recent_projects)
    route = inspect.getsource(MainWindow._open_project_path)

    assert "self._open_project_path" in regular
    assert "self._open_project_path" in recent
    assert "self._project_transition_ready()" in route
    assert "self._reset_project_runtime_state()" in route
    assert "self._resolve_missing_project_source" in route
    assert "self.load_csv(update_project=False)" in route
    assert "self.restore_project_queue()" in route


def test_h43_missing_source_picker_persists_user_relocation() -> None:
    from app.gui.main import MainWindow

    source = inspect.getsource(MainWindow._resolve_missing_project_source)

    assert "Locate project source" in source
    assert "state.project_file.parent / state.csv_path.name" in source
    assert "self.project_controller.update_csv_path(replacement)" in source
    assert "self.project_controller.autosave_if_needed(generation_active=False)" in source


def test_h43_close_project_performs_project_scoped_teardown_and_is_discoverable() -> None:
    from app.gui.main import MainWindow

    close = inspect.getsource(MainWindow.close_project)
    reset = inspect.getsource(MainWindow._reset_project_runtime_state)
    menu = inspect.getsource(MainWindow.build_project_menu)

    assert "self._project_transition_ready()" in close
    assert "self._reset_project_runtime_state()" in close
    assert "self.project_controller.close_project()" in close
    assert "self.audio_player_service.unload()" in reset
    assert "self.generation_controller.clear_jobs()" in reset
    assert "self.monitor_service.reset()" in reset
    assert "self.preflight_service.invalidate()" in reset
    assert "('Close Project','Ctrl+Shift+W')" in menu


def test_h43_transition_does_not_force_stop_or_start_generation() -> None:
    from app.gui.main import MainWindow

    ready = inspect.getsource(MainWindow._project_transition_ready)
    route = inspect.getsource(MainWindow._open_project_path)

    assert ".stop()" not in ready
    assert "self.start(" not in route
    assert "self.generate(" not in route
