from __future__ import annotations

import json
import uuid
import weakref
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool, Qt
from PySide6.QtWidgets import QApplication, QDialog

from app.models.qt_runtime_health import QtDialogLifecycleRecord, QtRuntimeHealthSnapshot


class QtRuntimeHealthService(QObject):
    """Track top-level dialog lifecycles without retaining Qt objects strongly."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dialogs: weakref.WeakValueDictionary[str, QDialog] = weakref.WeakValueDictionary()
        self._records: dict[str, QtDialogLifecycleRecord] = {}
        self._peak_registered = 0
        self._created_total = 0
        self._finished_total = 0
        self._destroyed_total = 0

    def register_dialog(self, dialog: QDialog, *, category: str = "report") -> str:
        existing = str(dialog.property("qtRuntimeHealthToken") or "")
        if existing and existing in self._records:
            return existing
        token = uuid.uuid4().hex
        dialog.setProperty("qtRuntimeHealthToken", token)
        if not dialog.testAttribute(Qt.WA_DeleteOnClose):
            dialog.setAttribute(Qt.WA_DeleteOnClose)
        record = QtDialogLifecycleRecord(
            token=token,
            class_name=type(dialog).__name__,
            object_name=dialog.objectName(),
            title=dialog.windowTitle(),
            category=category,
            visible=dialog.isVisible(),
            modal=dialog.isModal(),
            created_at=self._now(),
        )
        self._dialogs[token] = dialog
        self._records[token] = record
        self._created_total += 1
        self._peak_registered = max(self._peak_registered, len(self._dialogs))
        dialog.finished.connect(lambda result, key=token: self._mark_finished(key, int(result)))
        dialog.destroyed.connect(lambda _obj=None, key=token: self._mark_destroyed(key))
        return token

    def active_dialogs(self) -> list[QDialog]:
        return [dialog for dialog in self._dialogs.values() if dialog is not None]

    def snapshot(self) -> QtRuntimeHealthSnapshot:
        app = QApplication.instance()
        top_levels = list(app.topLevelWidgets()) if app is not None else []
        active_records: list[QtDialogLifecycleRecord] = []
        hidden = 0
        stale = 0
        for token, record in list(self._records.items()):
            dialog = self._dialogs.get(token)
            if dialog is None:
                if record.state == "active":
                    stale += 1
                continue
            visible = dialog.isVisible()
            if not visible and record.state == "active":
                hidden += 1
            active_records.append(
                replace(
                    record,
                    object_name=dialog.objectName(),
                    title=dialog.windowTitle(),
                    visible=visible,
                    modal=dialog.isModal(),
                )
            )
        return QtRuntimeHealthSnapshot(
            captured_at=self._now(),
            platform_name=app.platformName() if app is not None else "unavailable",
            registered_active=sum(item.state == "active" for item in active_records),
            hidden_registered=hidden,
            top_level_widgets=len(top_levels),
            visible_top_levels=sum(widget.isVisible() for widget in top_levels),
            active_thread_count=QThreadPool.globalInstance().activeThreadCount(),
            peak_registered=self._peak_registered,
            created_total=self._created_total,
            finished_total=self._finished_total,
            destroyed_total=self._destroyed_total,
            stale_reference_count=stale,
            records=tuple(sorted(active_records, key=lambda item: (item.category, item.class_name, item.created_at))),
        )

    def close_hidden_dialogs(self) -> int:
        count = 0
        for dialog in self.active_dialogs():
            if not dialog.isVisible():
                dialog.close()
                dialog.deleteLater()
                count += 1
        self.flush_deferred_deletes()
        return count

    def close_all(self) -> int:
        dialogs = self.active_dialogs()
        for dialog in dialogs:
            dialog.close()
            dialog.deleteLater()
        self.flush_deferred_deletes()
        return len(dialogs)

    @staticmethod
    def flush_deferred_deletes() -> None:
        app = QApplication.instance()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        if app is not None:
            app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def export_snapshot(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = directory / f"qt-runtime-health-{stamp}.json"
        path.write_text(json.dumps(self.snapshot().to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _mark_finished(self, token: str, result: int) -> None:
        record = self._records.get(token)
        if record is None or record.state != "active":
            return
        self._records[token] = replace(record, state="finished", finished_at=self._now(), result=result)
        self._finished_total += 1

    def _mark_destroyed(self, token: str) -> None:
        record = self._records.get(token)
        if record is not None and record.state != "destroyed":
            self._records[token] = replace(record, state="destroyed", finished_at=record.finished_at or self._now())
            self._destroyed_total += 1
        self._dialogs.pop(token, None)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
