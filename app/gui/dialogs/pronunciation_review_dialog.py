from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_assurance import PronunciationAssessment
from app.services.pronunciation_assurance_service import PronunciationAssuranceService


class PronunciationReviewDialog(QDialog):
    """Explicit batch pronunciation review without automatic execution.

    Opening, filtering, or selecting rows never mutates jobs and never runs
    Preflight, synthesis, routing, or language detection. A decision is emitted
    only after the user selects rows and presses a decision button.
    """

    decisionRequested = Signal(object, str)
    revalidateRequested = Signal(object)
    probeRequested = Signal(object)

    FILTER_NEEDS_REVIEW = "Needs review"
    FILTER_HIGH = "High risk"
    FILTER_MEDIUM = "Medium risk"
    FILTER_NORMALIZABLE = "Safe normalized candidate"
    FILTER_REVIEWED = "Reviewed · current"
    FILTER_STALE = "Needs revalidation"
    FILTER_ALL = "All review candidates"

    def __init__(
        self,
        jobs: tuple[TTSJob, ...],
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.jobs = jobs
        self.settings = settings
        self.assurance = PronunciationAssuranceService()
        self.assessments: dict[int, PronunciationAssessment] = {}
        self.batch = self.assurance.assess_batch(list(jobs), settings, require_freshness=True)
        self._refresh_assessments()

        self.setWindowTitle("Pronunciation Review Workspace")
        self.resize(1180, 720)
        root = QVBoxLayout(self)

        title = QLabel("Pronunciation Review Workspace")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Review pronunciation-risk rows at batch scale. Decisions are explicit per selected row. "
            "The source text and selected language are never changed; no preview, Preflight, generation, "
            "provider, account, voice, model, or language switch starts automatically."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("dialogSubtitle")
        root.addWidget(subtitle)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search row, text, flag, language or decision")
        self.search.textChanged.connect(self.refresh_table)
        controls.addWidget(self.search, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(
            [
                self.FILTER_NEEDS_REVIEW,
                self.FILTER_HIGH,
                self.FILTER_MEDIUM,
                self.FILTER_NORMALIZABLE,
                self.FILTER_REVIEWED,
                self.FILTER_STALE,
                self.FILTER_ALL,
            ]
        )
        self.filter_combo.currentTextChanged.connect(self.refresh_table)
        controls.addWidget(self.filter_combo)
        root.addLayout(controls)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Row", "Risk", "Language", "Signals", "Decision", "Freshness", "Source", "Normalized candidate", "Filename"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in {0: 70, 1: 85, 2: 90, 3: 190, 4: 175, 5: 120, 6: 280, 7: 280}.items():
            self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 1)

        self.selection_label = QLabel("Select one or more rows to record an explicit pronunciation decision.")
        self.selection_label.setWordWrap(True)
        root.addWidget(self.selection_label)

        actions = QHBoxLayout()
        self.original_button = QPushButton("Use original for selected")
        self.original_button.setToolTip("Record an explicit reviewed decision while keeping provider text unchanged.")
        self.original_button.clicked.connect(lambda: self._request_decision("original"))
        actions.addWidget(self.original_button)

        self.normalized_button = QPushButton("Use normalized for selected")
        self.normalized_button.setToolTip("Available only when every selected row has a safe language-locked candidate.")
        self.normalized_button.clicked.connect(lambda: self._request_decision("normalized"))
        actions.addWidget(self.normalized_button)

        self.revalidate_button = QPushButton("Revalidate selected decisions")
        self.revalidate_button.setToolTip("Refresh freshness evidence without changing original vs normalized intent.")
        self.revalidate_button.clicked.connect(self._request_revalidation)
        actions.addWidget(self.revalidate_button)

        self.clear_button = QPushButton("Clear decision")
        self.clear_button.clicked.connect(lambda: self._request_decision(""))
        actions.addWidget(self.clear_button)

        self.probe_button = QPushButton("Language Probe selected (1-3)")
        self.probe_button.clicked.connect(self._request_probe)
        actions.addWidget(self.probe_button)
        actions.addStretch(1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        root.addLayout(actions)

        self.refresh_table()
        self._update_action_state()

    def _refresh_assessments(self) -> None:
        parent_settings = getattr(self.parent(), "settings", None)
        if callable(parent_settings):
            self.settings = parent_settings()
        self.batch = self.assurance.assess_batch(list(self.jobs), self.settings, require_freshness=True)
        self.assessments = {
            int(item.row): item
            for item in self.batch.assessments
            if item.row is not None
        }

    def refresh_decisions(self) -> None:
        self._refresh_assessments()
        self.refresh_table()
        self._update_action_state()

    def _candidate_rows(self) -> list[int]:
        rows: list[int] = []
        for job in self.jobs:
            item = self.assessments.get(job.row_number)
            if item is None:
                continue
            override = str(getattr(job, "pronunciation_override", None) or "").strip()
            decision = self.assurance.decision_kind(override)
            if item.risk_level in {"high", "medium"} or item.normalization_safe or decision in {"original", "normalized"}:
                rows.append(job.row_number)
        return rows

    def _matches_filter(self, job: TTSJob, item: PronunciationAssessment, selected_filter: str) -> bool:
        override = str(getattr(job, "pronunciation_override", None) or "").strip()
        decision = self.assurance.decision_kind(override)
        freshness = self.assurance.decision_freshness(job, self.settings)
        reviewed = decision == "original" or (decision == "normalized" and item.normalization_safe)
        current = reviewed and freshness == "current"
        if selected_filter == self.FILTER_NEEDS_REVIEW:
            return item.risk_level in {"high", "medium"} and not current
        if selected_filter == self.FILTER_HIGH:
            return item.risk_level == "high"
        if selected_filter == self.FILTER_MEDIUM:
            return item.risk_level == "medium"
        if selected_filter == self.FILTER_NORMALIZABLE:
            return item.normalization_safe
        if selected_filter == self.FILTER_REVIEWED:
            return current
        if selected_filter == self.FILTER_STALE:
            return reviewed and freshness in {"stale", "legacy"}
        return True

    def _decision_label(self, job: TTSJob, item: PronunciationAssessment) -> str:
        override = str(getattr(job, "pronunciation_override", None) or "").strip()
        decision = self.assurance.decision_kind(override)
        if decision == "original":
            return "Reviewed · original"
        if decision == "normalized":
            return "Reviewed · normalized" if item.normalization_safe else "Invalid · normalized unavailable"
        if override:
            return override
        return "Not reviewed"

    def _freshness_label(self, job: TTSJob) -> str:
        status = self.assurance.decision_freshness(job, self.settings)
        return {"current": "Current", "stale": "Stale", "legacy": "Legacy", "none": "—"}.get(status, status.title())

    def refresh_table(self) -> None:
        selected_rows = set(self.selected_rows()) if hasattr(self, "table") else set()
        selected_filter = self.filter_combo.currentText() if hasattr(self, "filter_combo") else self.FILTER_NEEDS_REVIEW
        needle = self.search.text().strip().casefold() if hasattr(self, "search") else ""
        jobs_by_row = {job.row_number: job for job in self.jobs}
        rows: list[tuple[TTSJob, PronunciationAssessment]] = []
        for row in self._candidate_rows():
            job = jobs_by_row[row]
            item = self.assessments[row]
            if not self._matches_filter(job, item, selected_filter):
                continue
            decision = self._decision_label(job, item)
            haystack = " ".join(
                [
                    str(row),
                    job.filename,
                    job.text,
                    item.language,
                    item.risk_level,
                    " ".join(item.flags),
                    decision,
                    item.normalized_text if item.normalization_safe else "",
                ]
            ).casefold()
            if needle and needle not in haystack:
                continue
            rows.append((job, item))

        risk_rank = {"high": 0, "medium": 1, "low": 2}
        rows.sort(key=lambda pair: (risk_rank.get(pair[1].risk_level, 9), pair[0].row_number))
        self.table.setRowCount(len(rows))
        for table_row, (job, item) in enumerate(rows):
            values = [
                str(job.row_number),
                item.risk_level.title(),
                item.language or "not set",
                ", ".join(item.flags) if item.flags else "plain prose",
                self._decision_label(job, item),
                self._freshness_label(job),
                job.text,
                item.normalized_text if item.normalization_safe else "—",
                job.filename,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, int(job.row_number))
                self.table.setItem(table_row, column, cell)
            if job.row_number in selected_rows:
                self.table.selectRow(table_row)

        self.summary_label.setText(
            f"{self.batch.summary} Visible review candidates: {len(rows):,}. "
            f"Current: {len(self.batch.reviewed_rows):,}; "
            f"stale: {len(self.batch.stale_review_rows):,}; legacy: {len(self.batch.legacy_review_rows):,}; "
            f"explicit original: {len(self.batch.explicit_original_rows):,}; normalized: {len(self.batch.normalized_rows):,}."
        )

    def selected_rows(self) -> tuple[int, ...]:
        if not hasattr(self, "table") or self.table.selectionModel() is None:
            return ()
        rows = {
            int(self.table.item(index.row(), 0).data(Qt.UserRole))
            for index in self.table.selectionModel().selectedRows()
            if self.table.item(index.row(), 0) is not None
        }
        return tuple(sorted(rows))

    def _update_action_state(self) -> None:
        rows = self.selected_rows()
        selected = bool(rows)
        self.original_button.setEnabled(selected)
        self.clear_button.setEnabled(selected)
        self.probe_button.setEnabled(1 <= len(rows) <= 3)
        revalidatable = selected and all(
            self.assurance.decision_kind(getattr(next(job for job in self.jobs if job.row_number == row), "pronunciation_override", None))
            in {"original", "normalized"}
            for row in rows
        )
        normalized_revalidatable = revalidatable and all(
            self.assurance.decision_kind(getattr(next(job for job in self.jobs if job.row_number == row), "pronunciation_override", None)) != "normalized"
            or self.assessments[row].normalization_safe
            for row in rows
        )
        self.revalidate_button.setEnabled(normalized_revalidatable)
        safe = selected and all(self.assessments[row].normalization_safe for row in rows)
        self.normalized_button.setEnabled(safe)
        if not selected:
            text = "Select one or more rows to record an explicit pronunciation decision."
        elif safe:
            text = f"{len(rows)} row(s) selected. Original or safe normalized form can be chosen explicitly."
        else:
            unsafe = [row for row in rows if not self.assessments[row].normalization_safe]
            text = (
                f"{len(rows)} row(s) selected. Normalized action is disabled because "
                f"{len(unsafe)} selected row(s) have no safe language-locked candidate."
            )
        self.selection_label.setText(text)

    def _request_decision(self, decision: str) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        if decision == "normalized":
            unsafe = [row for row in rows if not self.assessments[row].normalization_safe]
            if unsafe:
                QMessageBox.warning(
                    self,
                    "Normalized form unavailable",
                    "No changes were made. Every selected row must have a safe language-locked normalized candidate.",
                )
                return
        self.decisionRequested.emit(rows, decision)
        self.refresh_decisions()

    def _request_revalidation(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        self.revalidateRequested.emit(rows)

    def _request_probe(self) -> None:
        rows = self.selected_rows()
        if not 1 <= len(rows) <= 3:
            QMessageBox.information(self, "Language Probe", "Select between 1 and 3 rows for manual probing.")
            return
        self.probeRequested.emit(rows)
