from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.models.domain import TTSJob


class QueueColumn(IntEnum):
    SOURCE_ROW = 0
    FILENAME = 1
    SOURCE = 2
    WORKSHEET = 3
    CHARACTERS = 4
    STATUS = 5
    PROVIDER = 6
    VOICE = 7
    MODEL = 8
    DURATION = 9
    RETRY = 10
    OUTPUT = 11


QUEUE_HEADERS: tuple[str, ...] = (
    "Source row",
    "Filename",
    "Source",
    "Worksheet",
    "Characters",
    "Status",
    "Provider",
    "Voice",
    "Model",
    "Duration",
    "Retry",
    "Output",
)


class QueueDataRole(IntEnum):
    """Stable custom roles shared by delegates, tests and the future view."""

    JOB_ID = Qt.UserRole + 1
    SORT_VALUE = Qt.UserRole + 2
    PROGRESS = Qt.UserRole + 3
    JOB = Qt.UserRole + 4


class QueueTableModel(QAbstractTableModel):
    """Read-only queue model prepared for the QTableView migration.

    Phase 1 deliberately does not replace the existing QTableWidget. The model
    is an independent adapter over the controller's TTSJob sequence so it can be
    tested and adopted incrementally without changing generation behaviour.
    """

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._jobs: list[TTSJob] = []
        self._default_provider = ""
        self._default_voice = ""
        self._default_model = ""
        self._default_source = "—"
        self._output_paths: dict[int, Path] = {}
        self._progress: dict[int, float] = {}
        self._row_by_job_id: dict[int, int] = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._jobs)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(QUEUE_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(QUEUE_HEADERS):
            return QUEUE_HEADERS[section]
        if orientation == Qt.Vertical and 0 <= section < len(self._jobs):
            return str(section + 1)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._jobs)):
            return None

        job = self._jobs[index.row()]
        column = QueueColumn(index.column())
        job_id = self.job_id(job)

        if role == QueueDataRole.JOB_ID:
            return job_id
        if role == QueueDataRole.JOB:
            return job
        if role == QueueDataRole.PROGRESS:
            return self._progress.get(job_id)
        if role == QueueDataRole.SORT_VALUE:
            return self._sort_value(job, column)
        if role == Qt.ToolTipRole:
            return self._tooltip(job, column)
        if role == Qt.TextAlignmentRole and column in {
            QueueColumn.SOURCE_ROW,
            QueueColumn.CHARACTERS,
            QueueColumn.DURATION,
            QueueColumn.RETRY,
        }:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.AccessibleTextRole and column == QueueColumn.STATUS:
            return f"Status: {job.status.value}"
        if role != Qt.DisplayRole:
            return None
        return self._display_value(job, column)

    def set_jobs(
        self,
        jobs: Sequence[TTSJob] | Iterable[TTSJob],
        *,
        default_provider: str = "",
        default_voice: str = "",
        default_model: str = "",
        default_source: str = "—",
        output_paths: dict[int, Path] | None = None,
        progress: dict[int, float] | None = None,
    ) -> None:
        """Replace the visible snapshot in one reset operation.

        The model stores the job objects themselves, not copied dictionaries, so
        identity remains stable and later incremental updates can target rows by
        job id without rebuilding the whole table.
        """

        snapshot = list(jobs)
        self.beginResetModel()
        self._jobs = snapshot
        self._default_provider = default_provider
        self._default_voice = default_voice
        self._default_model = default_model
        self._default_source = default_source
        self._output_paths = dict(output_paths or {})
        self._progress = dict(progress or {})
        self._row_by_job_id = {self.job_id(job): row for row, job in enumerate(snapshot)}
        self.endResetModel()

    def jobs(self) -> tuple[TTSJob, ...]:
        return tuple(self._jobs)

    def job_at(self, row: int) -> TTSJob | None:
        return self._jobs[row] if 0 <= row < len(self._jobs) else None

    def row_for_job_id(self, job_id: int) -> int | None:
        return self._row_by_job_id.get(job_id)

    def update_job(self, job: TTSJob, *, progress: float | None = None) -> bool:
        """Refresh one existing row without resetting selection or scroll state."""

        job_id = self.job_id(job)
        row = self._row_by_job_id.get(job_id)
        if row is None:
            return False
        self._jobs[row] = job
        if progress is not None:
            self._progress[job_id] = max(0.0, min(100.0, float(progress)))
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, self.columnCount() - 1),
            [Qt.DisplayRole, Qt.ToolTipRole, QueueDataRole.SORT_VALUE, QueueDataRole.PROGRESS],
        )
        return True

    def set_progress(self, job_id: int, progress: float | None) -> bool:
        row = self._row_by_job_id.get(job_id)
        if row is None:
            return False
        if progress is None:
            self._progress.pop(job_id, None)
        else:
            self._progress[job_id] = max(0.0, min(100.0, float(progress)))
        index = self.index(row, QueueColumn.STATUS)
        self.dataChanged.emit(index, index, [QueueDataRole.PROGRESS])
        return True

    @staticmethod
    def job_id(job: TTSJob) -> int:
        # row_number is the established identity used throughout the current UI
        # and is preserved here for a no-risk incremental migration.
        return int(job.row_number)

    def _display_value(self, job: TTSJob, column: QueueColumn) -> str | int:
        if column == QueueColumn.SOURCE_ROW:
            return job.source_row or job.row_number
        if column == QueueColumn.FILENAME:
            return job.filename
        if column == QueueColumn.SOURCE:
            return job.source_display_name or self._default_source
        if column == QueueColumn.WORKSHEET:
            return job.source_sheet or "—"
        if column == QueueColumn.CHARACTERS:
            return f"{job.character_count:,}"
        if column == QueueColumn.STATUS:
            return job.status.value
        if column == QueueColumn.PROVIDER:
            return job.provider_override or self._default_provider or "—"
        if column == QueueColumn.VOICE:
            return job.voice_override or self._default_voice or "—"
        if column == QueueColumn.MODEL:
            return job.model_override or self._default_model or "—"
        if column == QueueColumn.DURATION:
            return f"{job.duration_seconds:.2f}s" if job.duration_seconds else "—"
        if column == QueueColumn.RETRY:
            return job.retry_count
        if column == QueueColumn.OUTPUT:
            path = self._output_paths.get(self.job_id(job))
            return path.name if path else (Path(job.generated_output_path).name if job.generated_output_path else "—")
        raise AssertionError(f"Unsupported queue column: {column}")

    def _sort_value(self, job: TTSJob, column: QueueColumn) -> Any:
        if column == QueueColumn.SOURCE_ROW:
            return job.source_row or job.row_number
        if column == QueueColumn.CHARACTERS:
            return job.character_count
        if column == QueueColumn.DURATION:
            return job.duration_seconds
        if column == QueueColumn.RETRY:
            return job.retry_count
        value = self._display_value(job, column)
        return value.casefold() if isinstance(value, str) else value

    def _tooltip(self, job: TTSJob, column: QueueColumn) -> str:
        if column == QueueColumn.OUTPUT:
            path = self._output_paths.get(self.job_id(job))
            if path:
                return str(path)
            if job.generated_output_path:
                return job.generated_output_path
        return str(self._display_value(job, column))
