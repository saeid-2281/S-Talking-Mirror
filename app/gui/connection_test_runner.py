from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class ConnectionTestWorker(QObject):
    finished = Signal(object)

    def __init__(self, service, settings) -> None:
        super().__init__()
        self.service = service
        self.settings = settings

    def run(self) -> None:
        self.finished.emit(self.service.test_connection(self.settings))


def start_connection_test(parent, service, settings, finished_callback):
    thread = QThread(parent)
    worker = ConnectionTestWorker(service, settings)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(finished_callback)
    worker.finished.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker
