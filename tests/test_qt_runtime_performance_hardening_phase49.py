from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog

from app.gui.dialogs.qt_runtime_health_dialog import QtRuntimeHealthDialog
from app.models.qt_runtime_health import QtRuntimeHealthSnapshot
from app.services.qt_runtime_health_service import QtRuntimeHealthService


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_phase49_snapshot_status_reports_attention_for_hidden_dialog(qt_app) -> None:
    service = QtRuntimeHealthService()
    dialog = QDialog()
    service.register_dialog(dialog)
    snapshot = service.snapshot()
    assert snapshot.hidden_registered == 1
    assert snapshot.status == "attention"
    dialog.deleteLater()
    _drain(qt_app)


def test_phase49_registry_releases_dialog_without_strong_reference_cycle(qt_app) -> None:
    service = QtRuntimeHealthService()
    dialog = QDialog()
    token = service.register_dialog(dialog)
    dialog.show()
    qt_app.processEvents()
    dialog.close()
    dialog.deleteLater()
    _drain(qt_app)
    assert token not in {record.token for record in service.snapshot().records}
    assert service.snapshot().destroyed_total >= 1


def test_phase49_repeated_dialog_cycles_leave_registry_empty(qt_app) -> None:
    service = QtRuntimeHealthService()
    for index in range(25):
        dialog = QDialog()
        dialog.setObjectName(f"probe{index}")
        service.register_dialog(dialog, category="probe")
        dialog.show()
        dialog.close()
        dialog.deleteLater()
    _drain(qt_app)
    snapshot = service.snapshot()
    assert snapshot.registered_active == 0
    assert snapshot.peak_registered <= 25
    assert snapshot.created_total == 25


def test_phase49_close_hidden_dialogs_drains_deferred_delete(qt_app) -> None:
    service = QtRuntimeHealthService()
    first = QDialog()
    second = QDialog()
    service.register_dialog(first)
    service.register_dialog(second)
    assert service.close_hidden_dialogs() == 2
    _drain(qt_app)
    assert service.snapshot().registered_active == 0


def test_phase49_export_snapshot_is_structured_and_secret_free(qt_app, tmp_path: Path) -> None:
    service = QtRuntimeHealthService()
    dialog = QDialog()
    dialog.setWindowTitle("Runtime probe")
    service.register_dialog(dialog)
    path = service.export_snapshot(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["platform_name"]
    assert payload["registered_active"] == 1
    text = path.read_text(encoding="utf-8").casefold()
    assert "api_key" not in text
    dialog.deleteLater()
    _drain(qt_app)


def test_phase49_runtime_health_dialog_renders_and_releases(qt_app, tmp_path: Path) -> None:
    service = QtRuntimeHealthService()
    tracked = QDialog()
    service.register_dialog(tracked)
    dialog = QtRuntimeHealthDialog(service, export_dir=tmp_path)
    service.register_dialog(dialog, category="runtime-health")
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "qtRuntimeHealthDialog"
    assert dialog.table.rowCount() >= 1
    exported = dialog.export_snapshot()
    assert exported.exists()
    dialog.close()
    tracked.close()
    dialog.deleteLater()
    tracked.deleteLater()
    _drain(qt_app)


def test_phase49_mainwindow_uses_central_report_dialog_tracker() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "def _show_report_dialog" in source
    assert "QtRuntimeHealthService(self)" in source
    assert "UI Runtime Health" in source
    assert "destroyed.connect(lambda *_: self.report_dialogs.remove" not in source


def test_phase49_snapshot_model_serializes_status() -> None:
    snapshot = QtRuntimeHealthSnapshot(captured_at="now", platform_name="offscreen")
    payload = snapshot.to_dict()
    assert payload["status"] == "healthy"
    assert payload["records"] == ()
