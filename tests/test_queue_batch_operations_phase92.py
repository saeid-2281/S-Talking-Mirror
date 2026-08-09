from __future__ import annotations

import ast
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.queue_batch_operations import QueueBatchOperationsWidget
from app.models.domain import JobStatus, TTSJob
from app.services.queue_batch_operations_service import QueueBatchOperationsService

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/gui/main.py"
DOC = ROOT / "docs/QUEUE_BATCH_OPERATIONS_PHASE92.md"


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, text="a" * 100, filename="one", status=JobStatus.PENDING),
        TTSJob(row_number=2, text="b" * 200, filename="two", status=JobStatus.FAILED),
        TTSJob(row_number=3, text="c" * 300, filename="three", status=JobStatus.PENDING, provider_override="mock"),
        TTSJob(row_number=4, text="d" * 400, filename="four", status=JobStatus.COMPLETED, voice_override="voice-b"),
    ]


def test_phase92_pending_and_failed_lenses_preserve_row_identity() -> None:
    service = QueueBatchOperationsService()
    jobs = _jobs()
    assert service.lens_job_ids("pending", jobs) == (1, 3)
    assert service.lens_job_ids("failed", jobs) == (2,)
    assert [job.row_number for job in jobs] == [1, 2, 3, 4]


def test_phase92_selected_lens_uses_existing_row_numbers() -> None:
    service = QueueBatchOperationsService()
    assert service.lens_job_ids("selected", _jobs(), selected_rows={4, 2}) == (2, 4)


def test_phase92_quota_lens_is_pending_prefix_only() -> None:
    service = QueueBatchOperationsService()
    assert service.lens_job_ids("quota", _jobs(), quota_remaining=350) == (1,)
    assert service.lens_job_ids("quota", _jobs(), quota_remaining=450) == (1, 3)
    assert service.lens_job_ids("quota", _jobs(), quota_remaining=None) == ()


def test_phase92_snapshot_reports_scope_and_counts() -> None:
    snapshot = QueueBatchOperationsService().snapshot(
        _jobs(), selected_rows={2, 3}, quota_remaining=450
    )
    assert snapshot.visible_jobs == 4
    assert snapshot.visible_characters == 1000
    assert snapshot.selected_jobs == 2
    assert snapshot.selected_characters == 500
    assert snapshot.pending_jobs == 2
    assert snapshot.failed_jobs == 1
    assert snapshot.quota_jobs == 2


def test_phase92_grouping_is_analytical_and_deterministic() -> None:
    service = QueueBatchOperationsService()
    jobs = _jobs()
    before = [job.row_number for job in jobs]
    status = service.snapshot(jobs, group_by="status")
    provider = service.snapshot(jobs, group_by="provider", default_provider="elevenlabs")
    voice = service.snapshot(jobs, group_by="voice", default_voice="voice-a")
    assert status.groups[0].label == "Pending"
    assert provider.groups[0].label == "elevenlabs"
    assert any(group.label == "voice-b" for group in voice.groups)
    assert [job.row_number for job in jobs] == before


def test_phase92_widget_emits_lens_scope_and_existing_action_codes(qt_app) -> None:
    widget = QueueBatchOperationsWidget()
    snapshot = QueueBatchOperationsService().snapshot(_jobs(), selected_rows={2})
    widget.update_snapshot(snapshot)
    lenses: list[str] = []
    actions: list[str] = []
    scopes: list[bool] = []
    widget.lensRequested.connect(lenses.append)
    widget.actionRequested.connect(actions.append)
    widget.useSelectionRequested.connect(lambda: scopes.append(True))
    widget.lens.setCurrentIndex(widget.lens.findData("failed"))
    widget.select_button.click()
    widget.scope_button.click()
    widget.bulk.menu().actions()[0].trigger()
    assert lenses == ["failed"]
    assert scopes == [True]
    assert actions == ["retry_failed"]
    assert "Pending 2" in widget.summary.text()
    widget.close()


def test_phase92_compact_mode_yields_vertical_space(qt_app) -> None:
    widget = QueueBatchOperationsWidget()
    widget.show()
    qt_app.processEvents()
    widget.set_compact_mode(True)
    qt_app.processEvents()
    assert widget.isHidden()
    assert widget.maximumHeight() == 0
    widget.focus_lens()
    qt_app.processEvents()
    assert not widget.isHidden()
    widget.close()


def test_phase92_main_routes_batch_actions_to_existing_commands() -> None:
    source = MAIN.read_text(encoding="utf-8")
    ast.parse(source)
    assert "QueueBatchOperationsWidget" in source
    assert "QueueBatchOperationsService" in source
    assert "def apply_queue_batch_lens(self,lens):" in source
    assert "def handle_queue_batch_action(self,code):" in source
    assert "def _sync_workspace_overlay_compact(self):" in source
    assert "'retry_failed':self.retry_failed" in source
    assert "'skip_selected':self.skip_selected" in source
    assert "'reset_selected':self.reset_selected" in source
    assert "'clear_completed':self.clear_completed" in source


def test_phase92_main_exposes_shortcut_and_palette_without_new_generation_path() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert "Ctrl+Alt+Q" in source
    assert "Queue: Batch Operations" in source
    assert "restore_selection(row_ids)" in source
    assert "self.start" not in source[source.index("def handle_queue_batch_action"):source.index("def focus_queue_batch_operations")]


def test_phase92_mainwindow_hosts_batch_lens(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    assert window.queue_workspace.root_layout.indexOf(window.queue_batch_operations) == 2
    assert window.actions_by_name["Queue Batch Operations"].shortcut().toString() == "Ctrl+Alt+Q"
    window.close()


def test_phase92_compact_workspace_hides_batch_lens(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    window.setGeometry(0, 0, 1366, 768)
    window.apply_workspace_preset("Compact")
    qt_app.processEvents()
    assert window.queue_batch_operations.isHidden()
    assert window.generation_journey.isHidden()
    window.focus_queue_batch_operations()
    qt_app.processEvents()
    assert not window.queue_batch_operations.isHidden()
    window.close()


def test_phase92_documentation_preserves_queue_contracts() -> None:
    text = DOC.read_text(encoding="utf-8")
    for phrase in (
        "never reorders",
        "row_number",
        "introduces no new mutation semantics",
        "Ctrl+Alt+Q",
    ):
        assert phrase in text
