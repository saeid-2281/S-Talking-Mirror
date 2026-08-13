from __future__ import annotations

from pathlib import Path

from app.gui.widgets.queue_batch_operations import QueueBatchOperationsWidget
from app.models.domain import JobStatus, TTSJob
from app.services.queue_batch_operations_service import QueueBatchOperationsService


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, text="a" * 100, filename="one", status=JobStatus.PENDING),
        TTSJob(row_number=2, text="b" * 200, filename="two", status=JobStatus.FAILED),
        TTSJob(row_number=3, text="c" * 300, filename="three", status=JobStatus.PENDING),
        TTSJob(row_number=4, text="d" * 400, filename="four", status=JobStatus.COMPLETED),
    ]


def test_a6_snapshot_exposes_active_lens_plan_without_mutating_jobs() -> None:
    service = QueueBatchOperationsService()
    jobs = _jobs()
    before = [(job.row_number, job.status) for job in jobs]

    snapshot = service.snapshot(
        jobs,
        selected_rows={2, 3},
        quota_remaining=450,
        lens="pending",
    )

    assert snapshot.lens == "pending"
    assert snapshot.lens_label == "Pending"
    assert snapshot.lens_jobs == 2
    assert snapshot.lens_characters == 400
    assert snapshot.completed_jobs == 1
    assert [(job.row_number, job.status) for job in jobs] == before


def test_a6_quota_plan_preview_uses_existing_pending_prefix_rule() -> None:
    snapshot = QueueBatchOperationsService().snapshot(
        _jobs(),
        quota_remaining=450,
        lens="quota",
    )

    assert snapshot.lens_jobs == 2
    assert snapshot.lens_characters == 400
    assert snapshot.lens_summary == "Quota-ready · 2 job(s) · 400 characters"


def test_a6_unknown_lens_falls_back_to_all_visible() -> None:
    snapshot = QueueBatchOperationsService().snapshot(_jobs(), lens="not-a-lens")

    assert snapshot.lens == "all"
    assert snapshot.lens_jobs == 4
    assert snapshot.lens_characters == 1000


def test_a6_widget_shows_plan_preview_and_valid_bulk_actions(qt_app) -> None:
    widget = QueueBatchOperationsWidget()
    snapshot = QueueBatchOperationsService().snapshot(
        _jobs(),
        selected_rows={2},
        lens="failed",
    )
    widget.update_snapshot(snapshot)

    assert "Failed · 1 job(s) · 200 characters" in widget.plan_preview.text()
    assert "generation scope changes only" in widget.plan_preview.text()
    assert widget.scope_button.isEnabled() is True
    assert widget.bulk_actions["retry_failed"].isEnabled() is True
    assert widget.bulk_actions["skip_selected"].isEnabled() is True
    assert widget.bulk_actions["reset_selected"].isEnabled() is True
    assert widget.bulk_actions["clear_completed"].isEnabled() is True
    widget.close()


def test_a6_widget_disables_contextless_bulk_actions(qt_app) -> None:
    pending_only = [
        TTSJob(
            row_number=1,
            text="hello",
            filename="one",
            status=JobStatus.PENDING,
        )
    ]
    widget = QueueBatchOperationsWidget()
    widget.update_snapshot(
        QueueBatchOperationsService().snapshot(pending_only, lens="pending")
    )

    assert widget.scope_button.isEnabled() is False
    assert widget.bulk_actions["retry_failed"].isEnabled() is False
    assert widget.bulk_actions["skip_selected"].isEnabled() is False
    assert widget.bulk_actions["reset_selected"].isEnabled() is False
    assert widget.bulk_actions["clear_completed"].isEnabled() is False
    widget.close()


def test_a6_lens_change_only_requests_preview_refresh(qt_app) -> None:
    widget = QueueBatchOperationsWidget()
    changed: list[str] = []
    selected: list[str] = []
    actions: list[str] = []

    widget.lensChanged.connect(changed.append)
    widget.lensRequested.connect(selected.append)
    widget.actionRequested.connect(actions.append)

    widget.lens.setCurrentIndex(widget.lens.findData("failed"))
    qt_app.processEvents()

    assert changed == ["failed"]
    assert selected == []
    assert actions == []
    widget.close()


def test_a6_main_refresh_passes_current_lens_to_read_only_snapshot() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def refresh_queue_batch_operations", 1)[1].split(
        "def apply_queue_batch_lens",
        1,
    )[0]

    assert "lens=str(self.queue_batch_operations.lens.currentData() or 'all')" in method
    assert "set_generation_selection" not in method
    assert "invalidate_preflight" not in method
    assert "self.start(" not in method


def test_a6_main_lens_selection_does_not_change_generation_scope() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def apply_queue_batch_lens", 1)[1].split(
        "def handle_queue_batch_action",
        1,
    )[0]

    assert "restore_selection(row_ids)" in method
    assert "Generation scope is unchanged" in method
    assert "Preflight has NOT run" in method
    assert "set_generation_selection" not in method
    assert "invalidate_preflight" not in method
    assert "self.start(" not in method


def test_a6_use_selection_as_scope_requires_nonempty_selection() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def use_selection_as_scope", 1)[1].split(
        "def use_current_sort_as_generation_order",
        1,
    )[0]

    assert "if not rows:" in method
    assert "Generation scope and Preflight state are unchanged" in method
    assert "set_generation_selection(rows)" in method
    assert "self.invalidate_preflight()" in method
    assert "Preflight was invalidated but has NOT run" in method
    assert "generation has NOT started" in method
    assert "self.dry_run(" not in method
    assert "self.start(" not in method


def test_a6_phase92_bulk_handlers_are_unchanged() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def handle_queue_batch_action", 1)[1].split(
        "def focus_queue_batch_operations",
        1,
    )[0]

    for token in (
        "'retry_failed':self.retry_failed",
        "'skip_selected':self.skip_selected",
        "'reset_selected':self.reset_selected",
        "'clear_completed':self.clear_completed",
    ):
        assert token in method


def test_a6_widget_keeps_historical_phase92_signals_and_controls() -> None:
    source = Path("app/gui/widgets/queue_batch_operations.py").read_text(
        encoding="utf-8"
    )

    for token in (
        "lensRequested = Signal(str)",
        "groupChanged = Signal(str)",
        "useSelectionRequested = Signal()",
        "actionRequested = Signal(str)",
        '("Pending", "pending")',
        '("Failed", "failed")',
        '("Current selection", "selected")',
        '("Quota-ready", "quota")',
    ):
        assert token in source


def test_a6_grouping_remains_analytical_only() -> None:
    source = Path("app/services/queue_batch_operations_service.py").read_text(
        encoding="utf-8"
    )

    group_method = source.split("def _groups", 1)[1]
    assert ".sort(" not in group_method
    assert "job.row_number =" not in group_method


def test_a6_database_schema_23_is_preserved(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "a6-schema.db")
    database.initialize()

    assert database.expected_schema_version == 23
    assert database.applied_schema_versions()[-1] == 23


def test_a6_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/queue_batch_operations.py"),
        Path("app/services/queue_batch_operations_service.py"),
        Path("app/gui/widgets/queue_batch_operations.py"),
        Path("app/gui/main.py"),
        Path("docs/QUEUE_PLANNING_BATCH_OPERATIONS_EXPERIENCE_ROADMAP2_A6.md"),
        Path(__file__),
    )

    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
