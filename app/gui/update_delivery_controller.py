from __future__ import annotations

from queue import Empty, Queue
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from app.models.update_delivery import UpdateCheckSnapshot
from app.services.update_delivery_service import UpdateDeliveryService


class _UpdateJob(QRunnable):
    def __init__(
        self,
        service: UpdateDeliveryService,
        operation: str,
        result_queue: Queue[tuple[str, Any]],
        *,
        feed_source: str = "",
        snapshot: UpdateCheckSnapshot | None = None,
        force: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.operation = operation
        self.result_queue = result_queue
        self.feed_source = feed_source
        self.snapshot = snapshot
        self.force = force

    @Slot()
    def run(self) -> None:
        try:
            if self.operation == "check":
                result = self.service.check_for_updates(
                    self.feed_source or None,
                    force=self.force,
                )
            elif self.operation == "download" and self.snapshot is not None:
                result = self.service.download_update(self.snapshot)
            else:
                raise RuntimeError(f"Unsupported update operation: {self.operation}")
        except Exception as exc:  # pragma: no cover - delivered through controller
            self.result_queue.put(("failed", (self.operation, str(exc))))
            return
        self.result_queue.put(("completed", (self.operation, result)))


class UpdateDeliveryController(QObject):
    """Run update checks and verified downloads outside the GUI thread."""

    started = Signal(str)
    completed = Signal(str, object)
    failed = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(
        self,
        service: UpdateDeliveryService,
        *,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self._job: _UpdateJob | None = None
        self._result_queue: Queue[tuple[str, Any]] = Queue()
        self._result_timer = QTimer(self)
        self._result_timer.setInterval(20)
        self._result_timer.timeout.connect(self._drain)

    @property
    def busy(self) -> bool:
        return self._job is not None

    def check(self, feed_source: str = "", *, force: bool = False) -> bool:
        return self._start(
            _UpdateJob(
                self.service,
                "check",
                self._result_queue,
                feed_source=feed_source,
                force=force,
            )
        )

    def download(self, snapshot: UpdateCheckSnapshot) -> bool:
        return self._start(
            _UpdateJob(
                self.service,
                "download",
                self._result_queue,
                snapshot=snapshot,
            )
        )

    def _start(self, job: _UpdateJob) -> bool:
        if self.busy:
            return False
        self._job = job
        self._result_timer.start()
        self.started.emit(job.operation)
        self.busy_changed.emit(True)
        self.thread_pool.start(job)
        return True

    @Slot()
    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self._result_queue.get_nowait()
            except Empty:
                break
            operation = str(payload[0])
            self._job = None
            self.busy_changed.emit(False)
            if kind == "completed":
                self.completed.emit(operation, payload[1])
            else:
                self.failed.emit(operation, str(payload[1]))
        if self._job is None and self._result_queue.empty():
            self._result_timer.stop()
