"""B8.2B Stage 2: serial, non-GUI run-ledger lifecycle evidence writes.

This queue serializes status and terminal events for a run; it does not control
providers, workers, queues, Preflight, or Generation.  The GUI persists the tiny
execution lifecycle sidecar before it enqueues any potentially large ledger IO.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


class RunLedgerDispatcher:
    """Serialize ledger file transitions without blocking the Qt event loop."""

    def __init__(self, ledger_service: object) -> None:
        self._ledger_service = ledger_service
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="st-run-ledger")
        self._closed = False
        self._report_callbacks = True

    def _submit(
        self,
        operation: str,
        path: Path,
        task: Callable[[], object],
        callback: Callable[[str, str, object | None, str], None],
    ) -> Future[object]:
        if self._closed:
            raise RuntimeError("Run-ledger dispatcher is closed")
        future = self._executor.submit(task)

        def completed(completed_future: Future[object]) -> None:
            try:
                result = completed_future.result()
                error = ""
            except Exception as exc:
                result = None
                # Do not log secrets, project names or provider payloads.
                error = type(exc).__name__
            if self._report_callbacks:
                try:
                    callback(operation, str(path), result, error)
                except RuntimeError:
                    # Qt may already have destroyed the receiver during exit.
                    pass

        future.add_done_callback(completed)
        return future

    def status(
        self,
        path: Path,
        status: str,
        metrics: dict[str, Any] | None,
        callback: Callable[[str, str, object | None, str], None],
    ) -> Future[object]:
        location = Path(path)
        # Snapshot mutable metrics *before* crossing threads; never hand Qt
        # objects or a mutable current-run pointer to the worker.
        snapshot = dict(metrics or {})
        return self._submit(
            "status", location,
            lambda: self._ledger_service.record_status(location, status, metrics=snapshot),
            callback,
        )

    def finalize(
        self,
        path: Path,
        result: str,
        callback: Callable[[str, str, object | None, str], None],
        **evidence: Any,
    ) -> Future[object]:
        location = Path(path)
        # Same single-worker FIFO as status(): a terminal transition cannot
        # overtake a queued pause, resume, or stop audit event.
        snapshot = dict(evidence)
        if isinstance(snapshot.get("summary"), dict):
            snapshot["summary"] = dict(snapshot["summary"])
        return self._submit(
            "finalize", location,
            lambda: self._ledger_service.finalize(location, result, **snapshot),
            callback,
        )

    def close(self) -> None:
        """Keep queued evidence jobs; suppress callbacks to a closing window."""
        self._closed = True
        self._report_callbacks = False
        self._executor.shutdown(wait=False, cancel_futures=False)
