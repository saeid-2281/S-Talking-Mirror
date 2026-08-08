from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QDialog

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.operations_workspace_dialog import OperationsWorkspaceDialog
from app.gui.main import MainWindow
from app.models.domain import JobStatus, TTSJob
from app.models.operations_command_center import OperationsCommandSnapshot, OperationsDomainStatus
from app.services.performance_stability_service import PerformanceStabilityService


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/gui/main.py"
SERVICE = ROOT / "app/services/performance_stability_service.py"
WORKSPACE = ROOT / "app/gui/dialogs/operations_workspace_dialog.py"
DOC = ROOT / "docs/FINAL_PERFORMANCE_MEMORY_PHASE86.md"


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _metrics(*, widgets: int = 12, gc_objects: int = 100) -> dict[str, int]:
    return {
        "rss_bytes": 128 * 1024**2,
        "python_heap_bytes": 8 * 1024**2,
        "python_peak_bytes": 9 * 1024**2,
        "process_thread_count": 4,
        "qt_active_thread_count": 1,
        "qt_widget_count": widgets,
        "qt_top_level_count": 2,
        "gc_object_count": gc_objects,
        "open_file_count": 0,
        "process_handle_count": 80,
    }


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def _job(row: int) -> TTSJob:
    return TTSJob(
        row_number=row,
        text=f"Text {row}",
        filename=f"file-{row}.mp3",
        status=JobStatus.PENDING,
    )


class _SnapshotService:
    def __init__(self) -> None:
        self.warning = False

    def snapshot(self, *, project_id: int | None = None) -> OperationsCommandSnapshot:
        domain = OperationsDomainStatus(
            code="billing",
            label="Billing",
            status="warning" if self.warning else "healthy",
            headline="Review required" if self.warning else "Billing is healthy",
            metric="1 review" if self.warning else "0 variance",
            detail="Verified financial evidence.",
            action_code="financial-audit",
        )
        return OperationsCommandSnapshot(
            snapshot_id="phase86",
            generated_at=datetime.now(timezone.utc).isoformat(),
            version="1.0.0",
            channel="stable",
            project_id=project_id,
            overall_status="attention" if self.warning else "healthy",
            status_summary="Review required" if self.warning else "All healthy",
            domains=(domain,),
        )


def test_phase86_background_sampler_skips_deep_enumeration(tmp_path: Path) -> None:
    service = PerformanceStabilityService(_runtime(tmp_path))
    calls: list[bool] = []

    def fake_default_metrics(*, deep: bool = True) -> dict[str, int]:
        calls.append(deep)
        return _metrics(widgets=12 if deep else 0, gc_objects=100 if deep else 0)

    service._default_metrics = fake_default_metrics  # type: ignore[method-assign]
    sample = service.collect_background_sample(queue_total=17, generation_active=True)

    assert calls == [False]
    assert sample.label == "background-light"
    assert sample.qt_widget_count == 0
    assert sample.gc_object_count == 0
    assert sample.rss_bytes > 0
    assert sample.queue_total == 17
    assert sample.generation_active is True


def test_phase86_manual_and_snapshot_samples_keep_full_diagnostics(tmp_path: Path) -> None:
    service = PerformanceStabilityService(_runtime(tmp_path))
    calls: list[bool] = []

    def fake_default_metrics(*, deep: bool = True) -> dict[str, int]:
        calls.append(deep)
        return _metrics(widgets=41, gc_objects=321)

    service._default_metrics = fake_default_metrics  # type: ignore[method-assign]
    manual = service.collect_sample(label="manual", persist=False)
    snapshot = service.snapshot()

    assert calls == [True, True]
    assert manual.qt_widget_count == 41
    assert manual.gc_object_count == 321
    assert snapshot.current_sample.qt_widget_count == 41


def test_phase86_custom_metric_provider_remains_backward_compatible(tmp_path: Path) -> None:
    calls = 0

    def provider() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return _metrics(widgets=22, gc_objects=222)

    service = PerformanceStabilityService(_runtime(tmp_path), metric_provider=provider)
    background = service.collect_background_sample()
    manual = service.collect_sample(persist=False)

    assert calls == 2
    assert background.qt_widget_count == 22
    assert background.gc_object_count == 222
    assert manual.qt_widget_count == 22


def test_phase86_report_dialogs_are_delete_on_close_and_released(qt_app, tmp_path: Path) -> None:
    window = MainWindow(create_application_context(create_service_container(_runtime(tmp_path))))
    dialog = QDialog(window)
    window._show_report_dialog(dialog, category="phase86-probe")

    assert dialog.testAttribute(Qt.WA_DeleteOnClose)
    assert dialog in window.report_dialogs

    dialog.close()
    _drain(qt_app)

    assert dialog not in window.report_dialogs
    assert shiboken6.isValid(dialog) is False
    window.close()


def test_phase86_legacy_queue_render_resolves_settings_once(qt_app, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S_TALKING_QUEUE_MODEL_VIEW", "0")
    window = MainWindow(create_application_context(create_service_container(_runtime(tmp_path))))
    window.generation_controller.set_jobs([_job(row) for row in range(1, 41)])

    original_settings = window.settings
    calls = 0

    def counted_settings():
        nonlocal calls
        calls += 1
        return original_settings()

    window.settings = counted_settings  # type: ignore[method-assign]
    window.render_queue()

    assert calls == 1
    assert window.table.rowCount() == 40
    window.close()


def test_phase86_queue_render_computes_scope_summary_once(qt_app, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S_TALKING_QUEUE_MODEL_VIEW", "0")
    window = MainWindow(create_application_context(create_service_container(_runtime(tmp_path))))
    window.generation_controller.set_jobs([_job(1), _job(2)])
    calls = 0

    def counted_scope_summary(_visible_jobs=None):
        nonlocal calls
        calls += 1

    window.update_queue_scope_summary = counted_scope_summary  # type: ignore[method-assign]
    window.render_queue()

    assert calls == 1
    window.close()


def test_phase86_operations_workspace_does_not_rebuild_unchanged_domain_rows(qt_app) -> None:
    service = _SnapshotService()
    dialog = OperationsWorkspaceDialog(service)
    first_item = dialog.domain_table.item(0, 0)
    first_button = dialog.domain_table.cellWidget(0, 4)

    dialog.refresh()

    assert dialog.domain_table.item(0, 0) is first_item
    assert dialog.domain_table.cellWidget(0, 4) is first_button
    dialog.close()


def test_phase86_operations_workspace_updates_when_domain_signature_changes(qt_app) -> None:
    service = _SnapshotService()
    dialog = OperationsWorkspaceDialog(service)
    first_item = dialog.domain_table.item(0, 0)
    assert dialog.tool_status_labels["financial-audit"].text() == "Healthy"

    service.warning = True
    dialog.refresh()

    assert dialog.domain_table.item(0, 0) is not first_item
    assert dialog.domain_table.item(0, 1).text() == "warning"
    assert dialog.tool_status_labels["financial-audit"].text() == "Warning"
    dialog.close()


def test_phase86_mainwindow_routes_periodic_sampling_to_lightweight_path() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert "collect_background_sample(" in source
    capture = source.split("def capture_performance_sample", 1)[1].split("def open_performance_stability", 1)[0]
    assert "collect_sample(label='background'" not in capture
    assert "dialog.setAttribute(Qt.WA_DeleteOnClose, True)" in source


def test_phase86_source_and_documentation_contracts() -> None:
    ast.parse(MAIN.read_text(encoding="utf-8"))
    ast.parse(SERVICE.read_text(encoding="utf-8"))
    ast.parse(WORKSPACE.read_text(encoding="utf-8"))
    documentation = DOC.read_text(encoding="utf-8")
    for phrase in (
        "behavior-preserving",
        "WA_DeleteOnClose",
        "background-light",
        "one settings resolution per queue render",
        "does not change generation semantics",
    ):
        assert phrase in documentation
