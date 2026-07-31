from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QObject, QPoint, QItemSelectionModel, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTableWidget

from app.gui.widgets.queue_table_model import QueueTableModel
from app.gui.widgets.queue_table_view import QueueTableView
from app.models.domain import TTSJob


@runtime_checkable
class QueueViewBackend(Protocol):
    """Small queue-view contract consumed by MainWindow during migration."""

    def job_ids(self) -> tuple[int, ...]: ...

    def selected_job_ids(self) -> set[int]: ...

    def selected_jobs(self) -> list[TTSJob]: ...

    def selected_view_rows(self) -> list[int]: ...

    def select_job_id(self, job_id: int, *, clear: bool = True, scroll: bool = True) -> bool: ...

    def select_view_row(self, row: int, *, clear: bool = True, scroll: bool = True) -> bool: ...

    def restore_selection(self, job_ids: Iterable[int]) -> None: ...

    def row_for_job_id(self, job_id: int) -> int | None: ...

    def job_at_view_row(self, row: int) -> TTSJob | None: ...

    def refresh_jobs(self, jobs: Sequence[TTSJob], **kwargs) -> None: ...  # noqa: ANN003

    def refresh_rows(self, jobs: Iterable[TTSJob]) -> int: ...

    def set_progress(self, job_id: int, progress: float | None) -> bool: ...

    def map_viewport_to_global(self, position: QPoint) -> QPoint: ...


class _TableWidgetBackend:
    """Compatibility implementation for the current QTableWidget queue."""

    def __init__(self, table: QTableWidget, jobs_provider: Callable[[], Sequence[TTSJob]]) -> None:
        self.table = table
        self.jobs_provider = jobs_provider

    def _jobs(self) -> list[TTSJob]:
        return list(self.jobs_provider())

    def selected_view_rows(self) -> list[int]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        rows = {index.row() for index in selection.selectedRows(0)}
        if not rows:
            # Some legacy tables are configured for item selection before the
            # queue adapter applies row flags. Falling back to selected indexes
            # keeps the adapter contract stable during the migration.
            rows = {index.row() for index in selection.selectedIndexes()}
        return sorted(rows)

    def _job_id_at_row(self, row: int) -> int | None:
        if not 0 <= row < self.table.rowCount():
            return None
        item = self.table.item(row, 0)
        if item is not None:
            value = item.data(Qt.UserRole)
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
        jobs = self._jobs()
        if 0 <= row < len(jobs):
            return int(jobs[row].row_number)
        return None

    def job_ids(self) -> tuple[int, ...]:
        return tuple(
            job_id
            for row in range(self.table.rowCount())
            if (job_id := self._job_id_at_row(row)) is not None
        )

    def selected_job_ids(self) -> set[int]:
        return {
            job_id
            for row in self.selected_view_rows()
            if (job_id := self._job_id_at_row(row)) is not None
        }

    def selected_jobs(self) -> list[TTSJob]:
        jobs_by_id = {int(job.row_number): job for job in self._jobs()}
        return [jobs_by_id[job_id] for job_id in self.selected_job_ids() if job_id in jobs_by_id]

    def row_for_job_id(self, job_id: int) -> int | None:
        target = int(job_id)
        for row in range(self.table.rowCount()):
            if self._job_id_at_row(row) == target:
                return row
        return None

    def job_at_view_row(self, row: int) -> TTSJob | None:
        jobs = self._jobs()
        return jobs[row] if 0 <= row < len(jobs) else None

    def select_job_id(self, job_id: int, *, clear: bool = True, scroll: bool = True) -> bool:
        row = self.row_for_job_id(job_id)
        if row is None:
            return False
        return self.select_view_row(row, clear=clear, scroll=scroll)

    def select_view_row(self, row: int, *, clear: bool = True, scroll: bool = True) -> bool:
        if not 0 <= row < self.table.rowCount():
            return False
        selection = self.table.selectionModel()
        if selection is None:
            return False
        index = self.table.model().index(row, 0)
        self.table.setCurrentCell(row, 0)
        flags = QItemSelectionModel.Rows
        flags |= QItemSelectionModel.ClearAndSelect if clear else QItemSelectionModel.Select
        selection.select(index, flags)
        if scroll:
            self.table.scrollToItem(self.table.item(row, 0), QAbstractItemView.PositionAtCenter)
        return True

    def restore_selection(self, job_ids: Iterable[int]) -> None:
        ids = {int(job_id) for job_id in job_ids}
        selection = self.table.selectionModel()
        if selection is None:
            return
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            for job_id in ids:
                row = self.row_for_job_id(job_id)
                if row is None:
                    continue
                index = self.table.model().index(row, 0)
                selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        finally:
            self.table.blockSignals(False)
        # QTableWidget does not emit after blockSignals(False), so callers that
        # need a refresh invoke their existing summary/preview updates.

    def refresh_jobs(self, jobs: Sequence[TTSJob], **kwargs) -> None:  # noqa: ARG002, ANN003
        # Rendering remains owned by MainWindow during the compatibility phase.
        # Keeping this method explicit prevents accidental model/view-only calls.
        return None

    def refresh_rows(self, jobs: Iterable[TTSJob]) -> int:  # noqa: ARG002
        # Legacy rows are still rendered by MainWindow.render_queue().
        return 0

    def set_progress(self, job_id: int, progress: float | None) -> bool:  # noqa: ARG002
        return False

    def map_viewport_to_global(self, position: QPoint) -> QPoint:
        return self.table.viewport().mapToGlobal(position)


class _TableViewBackend:
    """Model/view implementation backed by QueueTableView."""

    def __init__(self, view: QueueTableView) -> None:
        self.view = view

    def job_ids(self) -> tuple[int, ...]:
        return tuple(int(job.row_number) for job in self.view.queue_model.jobs())

    def selected_job_ids(self) -> set[int]:
        return self.view.selected_job_ids()

    def selected_jobs(self) -> list[TTSJob]:
        return self.view.selected_jobs()

    def selected_view_rows(self) -> list[int]:
        return self.view.selected_rows()

    def select_job_id(self, job_id: int, *, clear: bool = True, scroll: bool = True) -> bool:
        return self.view.select_job_id(job_id, clear=clear, scroll=scroll)

    def select_view_row(self, row: int, *, clear: bool = True, scroll: bool = True) -> bool:
        job = self.view.job_at_view_row(row)
        if job is None:
            return False
        return self.view.select_job_id(job.row_number, clear=clear, scroll=scroll)

    def restore_selection(self, job_ids: Iterable[int]) -> None:
        self.view.restore_selection(job_ids)

    def row_for_job_id(self, job_id: int) -> int | None:
        return self.view.queue_model.row_for_job_id(int(job_id))

    def job_at_view_row(self, row: int) -> TTSJob | None:
        return self.view.job_at_view_row(row)

    def refresh_jobs(self, jobs: Sequence[TTSJob], **kwargs) -> None:  # noqa: ANN003
        self.view.set_jobs(jobs, **kwargs)

    def refresh_rows(self, jobs: Iterable[TTSJob]) -> int:
        updated = 0
        model: QueueTableModel = self.view.queue_model
        for job in jobs:
            if model.update_job(job):
                updated += 1
        return updated

    def set_progress(self, job_id: int, progress: float | None) -> bool:
        return self.view.queue_model.set_progress(int(job_id), progress)

    def map_viewport_to_global(self, position: QPoint) -> QPoint:
        return self.view.viewport().mapToGlobal(position)


class QueueViewAdapter(QObject):
    """Stable queue API shared by legacy and model/view implementations.

    MainWindow can migrate one interaction at a time without branching on the
    concrete Qt table class. The adapter does not own business rules or copy job
    state; it only translates view operations into job-identity operations.
    """

    selection_changed = Signal()
    cell_double_clicked = Signal(int, int)
    context_menu_requested = Signal(QPoint)

    def __init__(
        self,
        view: QTableWidget | QueueTableView,
        *,
        jobs_provider: Callable[[], Sequence[TTSJob]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or view)
        self.view = view
        if isinstance(view, QueueTableView):
            self._backend: QueueViewBackend = _TableViewBackend(view)
            view.itemSelectionChanged.connect(self.selection_changed)
            view.cellDoubleClicked.connect(self.cell_double_clicked)
        elif isinstance(view, QTableWidget):
            if jobs_provider is None:
                raise TypeError("jobs_provider is required for a QTableWidget queue")
            self._backend = _TableWidgetBackend(view, jobs_provider)
            view.itemSelectionChanged.connect(self.selection_changed)
            view.cellDoubleClicked.connect(self.cell_double_clicked)
        else:
            raise TypeError(f"Unsupported queue view: {type(view).__name__}")
        view.customContextMenuRequested.connect(self.context_menu_requested)

    @property
    def is_model_view(self) -> bool:
        return isinstance(self.view, QueueTableView)

    def job_ids(self) -> tuple[int, ...]:
        return self._backend.job_ids()

    def selected_job_ids(self) -> set[int]:
        return self._backend.selected_job_ids()

    def selected_jobs(self) -> list[TTSJob]:
        return self._backend.selected_jobs()

    def selected_view_rows(self) -> list[int]:
        return self._backend.selected_view_rows()

    def current_job(self) -> TTSJob | None:
        current = self.view.currentIndex()
        return self._backend.job_at_view_row(current.row()) if current.isValid() else None

    def select_job_id(self, job_id: int, *, clear: bool = True, scroll: bool = True) -> bool:
        return self._backend.select_job_id(job_id, clear=clear, scroll=scroll)

    def select_view_row(self, row: int, *, clear: bool = True, scroll: bool = True) -> bool:
        return self._backend.select_view_row(row, clear=clear, scroll=scroll)

    def scroll_to_job(self, job_id: int) -> bool:
        return self._backend.select_job_id(job_id, clear=False, scroll=True)

    def restore_selection(self, job_ids: Iterable[int]) -> None:
        self._backend.restore_selection(job_ids)

    def row_for_job_id(self, job_id: int) -> int | None:
        return self._backend.row_for_job_id(job_id)

    def job_at_view_row(self, row: int) -> TTSJob | None:
        return self._backend.job_at_view_row(row)

    def refresh_jobs(self, jobs: Sequence[TTSJob], **kwargs) -> None:  # noqa: ANN003
        self._backend.refresh_jobs(jobs, **kwargs)

    def refresh_rows(self, jobs: Iterable[TTSJob]) -> int:
        return self._backend.refresh_rows(jobs)

    def set_progress(self, job_id: int, progress: float | None) -> bool:
        return self._backend.set_progress(job_id, progress)

    def map_viewport_to_global(self, position: QPoint) -> QPoint:
        return self._backend.map_viewport_to_global(position)
