from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.gui.worker import GenerationWorker
from app.models.domain import AppSettings, TTSJob
from app.models.ui_state import GenerationUiState


class GenerationController(QObject):
    """Owns generation worker and thread lifetime."""

    progress = Signal(int, int, str, str, float, int, str)
    log = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: Path) -> None:
        super().__init__()
        self.database_path = database_path
        self.worker: GenerationWorker | None = None
        self.thread: QThread | None = None
        self._state = GenerationUiState(jobs=[])
        self.current_project_key: str | None = None

    @property
    def is_active(self) -> bool:
        return self.worker is not None

    @property
    def is_paused(self) -> bool:
        return self._state.paused

    @property
    def jobs(self) -> list[TTSJob]:
        return self._state.jobs

    def set_jobs(self, jobs: list[TTSJob]) -> None:
        self._state.jobs = jobs

    def clear_jobs(self) -> None:
        self._state.jobs = []
        self._state.status = "idle"

    def has_jobs(self) -> bool:
        return bool(self._state.jobs)

    def start(
        self,
        parent: QObject,
        *args: object,
    ) -> bool:
        if len(args) == 4 and isinstance(args[0], list):
            jobs, settings, output_dir, project_key = args
            self.set_jobs(jobs)
        elif len(args) == 3:
            settings, output_dir, project_key = args
        else:
            raise TypeError("start expects settings, output_dir, project_key")

        if not isinstance(settings, AppSettings):
            raise TypeError("settings must be AppSettings")
        output_path = Path(output_dir)
        project_key_value = str(project_key)

        if self.is_active or not self.has_jobs():
            return False
        self.thread = QThread(parent)
        self.current_project_key = project_key_value
        self.worker = GenerationWorker(
            self.jobs,
            settings,
            output_path,
            self.database_path,
            project_key_value,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self._state.status = "running"
        self.thread.start()
        return True

    def pause(self) -> bool:
        if self.worker is None:
            return False
        self._state.paused = True
        self.worker.pause()
        return True

    def resume(self) -> bool:
        if self.worker is None:
            return False
        self._state.paused = False
        self.worker.resume()
        return True

    def stop(self) -> bool:
        if self.worker is None:
            return False
        self.worker.stop()
        return True

    def _finished(self, summary: dict) -> None:
        self.finished.emit(summary)
        self._clear()

    def _failed(self, error: str) -> None:
        self.failed.emit(error)
        self._clear()

    def _clear(self) -> None:
        self.worker = None
        self._state.paused = False
        self._state.status = "idle"
