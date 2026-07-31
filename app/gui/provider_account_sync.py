from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from time import perf_counter
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from app.models.domain import AppSettings
from app.models.elevenlabs import ProviderConnectionResult
from app.services.voice_service import VoiceCatalog, VoiceService


@dataclass(frozen=True)
class ProviderAccountSyncResult:
    profile_id: str
    request_id: int
    force_refresh: bool
    connection: ProviderConnectionResult
    catalog: VoiceCatalog | None
    latency_ms: int


class _SyncJob(QRunnable):
    """Run one account sync and publish a plain result to a thread-safe queue."""

    def __init__(
        self,
        *,
        profile_id: str,
        request_id: int,
        force_refresh: bool,
        settings: AppSettings,
        voice_service: VoiceService,
        result_queue: Queue[tuple[str, Any]],
    ) -> None:
        super().__init__()
        self.profile_id = profile_id
        self.request_id = request_id
        self.force_refresh = force_refresh
        self.settings = settings
        self.voice_service = voice_service
        self.result_queue = result_queue

    @Slot()
    def run(self) -> None:
        started = perf_counter()
        try:
            connection = self.voice_service.test_connection(
                self.settings,
                force_refresh=self.force_refresh,
            )
            catalog = self.voice_service.cached_catalog(self.settings)
            result = ProviderAccountSyncResult(
                profile_id=self.profile_id,
                request_id=self.request_id,
                force_refresh=self.force_refresh,
                connection=connection,
                catalog=catalog,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
            )
        except Exception as exc:  # pragma: no cover - exercised through controller contract
            self.result_queue.put(
                (
                    "failed",
                    (self.profile_id, self.request_id, str(exc)),
                )
            )
            return

        self.result_queue.put(("completed", result))


class ProviderAccountSyncController(QObject):
    """Coordinate independent background account refreshes.

    QRunnable-to-QObject signal forwarding behaves differently across PySide6
    releases. Workers therefore write plain results to a thread-safe queue,
    while a QTimer owned by this controller drains that queue on the GUI
    thread. Public signals are consequently emitted from one stable thread.

    Cancellation is logical: an in-flight provider request cannot always be
    interrupted safely, so cancelled or superseded responses are ignored.
    """

    started = Signal(str, int, bool)
    completed = Signal(object)
    failed = Signal(str, int, str)
    cancelled = Signal(str, int)
    busy_changed = Signal(str, bool)

    def __init__(
        self,
        voice_service: VoiceService,
        *,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.voice_service = voice_service
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self._next_request_id = 0
        self._active: dict[str, int] = {}
        self._cancelled: set[tuple[str, int]] = set()
        self._jobs: dict[tuple[str, int], _SyncJob] = {}
        self._result_queue: Queue[tuple[str, Any]] = Queue()

        self._result_timer = QTimer(self)
        self._result_timer.setInterval(10)
        self._result_timer.timeout.connect(self._drain_results)

    def start(
        self,
        profile_id: str,
        settings: AppSettings,
        *,
        force_refresh: bool,
    ) -> bool:
        profile_id = str(profile_id)
        if profile_id in self._active:
            return False

        self._next_request_id += 1
        request_id = self._next_request_id
        self._active[profile_id] = request_id

        job = _SyncJob(
            profile_id=profile_id,
            request_id=request_id,
            force_refresh=force_refresh,
            settings=settings,
            voice_service=self.voice_service,
            result_queue=self._result_queue,
        )
        self._jobs[(profile_id, request_id)] = job

        if not self._result_timer.isActive():
            self._result_timer.start()

        self.started.emit(profile_id, request_id, force_refresh)
        self.busy_changed.emit(profile_id, True)
        self.thread_pool.start(job)
        return True

    def cancel(self, profile_id: str) -> bool:
        profile_id = str(profile_id)
        request_id = self._active.get(profile_id)
        if request_id is None:
            return False

        self._cancelled.add((profile_id, request_id))
        self._active.pop(profile_id, None)
        self.busy_changed.emit(profile_id, False)
        self.cancelled.emit(profile_id, request_id)
        return True

    def cancel_all(self) -> None:
        for profile_id in tuple(self._active):
            self.cancel(profile_id)

    def is_busy(self, profile_id: str) -> bool:
        return str(profile_id) in self._active

    def active_profiles(self) -> tuple[str, ...]:
        return tuple(self._active)

    @Slot()
    def _drain_results(self) -> None:
        while True:
            try:
                kind, payload = self._result_queue.get_nowait()
            except Empty:
                break

            if kind == "completed":
                self._completed(payload)
            else:
                profile_id, request_id, message = payload
                self._failed(str(profile_id), int(request_id), str(message))

        if not self._jobs and self._result_queue.empty():
            self._result_timer.stop()

    def _completed(self, result: ProviderAccountSyncResult) -> None:
        key = (result.profile_id, result.request_id)
        self._jobs.pop(key, None)

        if key in self._cancelled:
            self._cancelled.discard(key)
            return
        if self._active.get(result.profile_id) != result.request_id:
            return

        self._active.pop(result.profile_id, None)
        self.busy_changed.emit(result.profile_id, False)
        self.completed.emit(result)

    def _failed(self, profile_id: str, request_id: int, message: str) -> None:
        key = (profile_id, request_id)
        self._jobs.pop(key, None)

        if key in self._cancelled:
            self._cancelled.discard(key)
            return
        if self._active.get(profile_id) != request_id:
            return

        self._active.pop(profile_id, None)
        self.busy_changed.emit(profile_id, False)
        self.failed.emit(profile_id, request_id, message)
