from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.gui.worker import GenerationWorker
from app.models.domain import AppSettings, TTSJob


class GenerationController(QObject):
    """Owns generation worker and thread lifetime."""

    progress = Signal(int, int, str, str, float, int, str)
    log = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: Path = Path("data/s-talking.db")) -> None:
        super().__init__()
        self.database_path = database_path
        self.worker: GenerationWorker | None = None
        self.thread: QThread | None = None
        self.paused = False

    @property
    def is_active(self) -> bool:
        return self.worker is not None

    def start(
        self,
        parent: QObject,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        project_key: str,
    ) -> bool:
        if self.is_active or not jobs:
            return False
        self.thread = QThread(parent)
        self.worker = GenerationWorker(jobs, settings, output_dir, self.database_path, project_key)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.start()
        return True

    def pause(self) -> bool:
        if self.worker is None:
            return False
        self.paused = True
        self.worker.pause()
        return True

    def resume(self) -> bool:
        if self.worker is None:
            return False
        self.paused = False
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
        self.paused = False
