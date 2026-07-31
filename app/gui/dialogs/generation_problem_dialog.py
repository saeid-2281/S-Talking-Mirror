from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_problem import GenerationKnownProblem
from app.services.generation_problem_service import GenerationProblemService


class KnownProblemEditorDialog(QDialog):
    def __init__(
        self,
        service: GenerationProblemService,
        problem: GenerationKnownProblem,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.problem = problem
        self.saved_problem: GenerationKnownProblem | None = None
        self.setWindowTitle("Edit Known Problem")
        self.resize(720, 660)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.status_combo = QComboBox()
        for value in (
            "investigating",
            "known_error",
            "fix_planned",
            "monitoring",
            "closed",
        ):
            self.status_combo.addItem(value.replace("_", " ").title(), value)
        self.severity_combo = QComboBox()
        self.severity_combo.addItem("Critical", "critical")
        self.severity_combo.addItem("Warning", "warning")
        self.category_combo = QComboBox()
        for value in sorted(GenerationProblemService.VALID_CATEGORIES):
            self.category_combo.addItem(value.replace("_", " ").title(), value)
        self.owner_edit = QLineEdit()
        self.monitoring_edit = QLineEdit()
        self.monitoring_edit.setPlaceholderText("ISO-8601 deadline, optional")
        self.description_edit = QPlainTextEdit()
        self.description_edit.setMaximumHeight(100)
        self.workaround_edit = QPlainTextEdit()
        self.workaround_edit.setMaximumHeight(110)
        self.permanent_fix_edit = QPlainTextEdit()
        self.permanent_fix_edit.setMaximumHeight(110)
        form.addRow("Title", self.title_edit)
        form.addRow("Status", self.status_combo)
        form.addRow("Severity", self.severity_combo)
        form.addRow("Root-cause category", self.category_combo)
        form.addRow("Owner", self.owner_edit)
        form.addRow("Monitoring until", self.monitoring_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Workaround", self.workaround_edit)
        form.addRow("Permanent fix", self.permanent_fix_edit)
        root.addLayout(form)
        self.status_label = QLabel()
        root.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load(self) -> None:
        self.title_edit.setText(self.problem.title)
        self.status_combo.setCurrentIndex(
            max(0, self.status_combo.findData(self.problem.status))
        )
        self.severity_combo.setCurrentIndex(
            max(0, self.severity_combo.findData(self.problem.severity))
        )
        self.category_combo.setCurrentIndex(
            max(0, self.category_combo.findData(self.problem.root_cause_category))
        )
        self.owner_edit.setText(self.problem.owner or "")
        self.monitoring_edit.setText(self.problem.monitoring_until or "")
        self.description_edit.setPlainText(self.problem.description)
        self.workaround_edit.setPlainText(self.problem.workaround)
        self.permanent_fix_edit.setPlainText(self.problem.permanent_fix)

    def save(self) -> None:
        try:
            self.saved_problem = self.service.update_problem(
                replace(
                    self.problem,
                    title=self.title_edit.text(),
                    status=str(self.status_combo.currentData()),
                    severity=str(self.severity_combo.currentData()),
                    root_cause_category=str(self.category_combo.currentData()),
                    owner=self.owner_edit.text() or None,
                    monitoring_until=self.monitoring_edit.text() or None,
                    description=self.description_edit.toPlainText(),
                    workaround=self.workaround_edit.toPlainText(),
                    permanent_fix=self.permanent_fix_edit.toPlainText(),
                )
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.accept()


class GenerationProblemDialog(QDialog):
    """Known-error registry with recurrence, workaround, and permanent-fix tracking."""

    def __init__(
        self,
        service: GenerationProblemService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.export_dir = export_dir or Path.cwd() / "reports" / "problems"
        self.all_problems: list[GenerationKnownProblem] = []
        self.filtered_problems: list[GenerationKnownProblem] = []
        self.setWindowTitle("Generation Problem Center")
        self.resize(1260, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Problem Management & Known Errors")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.current_project_only = QCheckBox("Current project only")
        self.current_project_only.setChecked(self.project_id is not None)
        self.current_project_only.setEnabled(self.project_id is not None)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", "")
        for value in (
            "investigating",
            "known_error",
            "fix_planned",
            "monitoring",
            "closed",
        ):
            self.status_filter.addItem(value.replace("_", " ").title(), value)
        self.category_filter = QComboBox()
        self.category_filter.addItem("All categories", "")
        for value in sorted(GenerationProblemService.VALID_CATEGORIES):
            self.category_filter.addItem(value.replace("_", " ").title(), value)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search problem, owner, fingerprint, workaround, permanent fix or incident"
        )
        filters.addWidget(self.current_project_only)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.category_filter)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Status",
                "Severity",
                "Occurrences",
                "Incidents",
                "Owner",
                "Category",
                "Last seen",
                "Title",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setSizes([430, 260])
        root.addWidget(splitter, 1)

        self.summary_label = QLabel()
        self.status_label = QLabel()
        root.addWidget(self.summary_label)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        for label, handler in (
            ("Create from incidents", self.create_from_incidents),
            ("Link incident", self.link_incident),
            ("Edit", self.edit_selected),
            ("Export filtered", self.export_filtered),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

        self.current_project_only.toggled.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.category_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.update_details)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_selected())

    def refresh(self) -> None:
        self.all_problems = self.service.list_problems(limit=1000)
        self.apply_filters()

    def apply_filters(self) -> None:
        project_id = (
            self.project_id
            if self.project_id is not None and self.current_project_only.isChecked()
            else None
        )
        status = str(self.status_filter.currentData() or "")
        category = str(self.category_filter.currentData() or "")
        search = self.search.text().strip().casefold()
        records = self.all_problems
        if project_id is not None:
            records = [item for item in records if item.project_id == project_id]
        if status:
            records = [item for item in records if item.status == status]
        if category:
            records = [item for item in records if item.root_cause_category == category]
        if search:
            records = [item for item in records if search in self._search_text(item)]
        self.filtered_problems = records
        self._populate_table()
        self._update_summary()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.filtered_problems))
        for row, problem in enumerate(self.filtered_problems):
            values = (
                self._label(problem.status),
                self._label(problem.severity),
                str(problem.occurrence_count),
                str(len(problem.incident_ids)),
                problem.owner or "Unassigned",
                self._label(problem.root_cause_category),
                self._short_timestamp(problem.last_seen_at),
                problem.title,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, problem.problem_id)
                self.table.setItem(row, column, item)
        self.table.clearSelection()
        self.details.clear()

    def _update_summary(self) -> None:
        summary = self.service.summary(self.filtered_problems)
        self.summary_label.setText(
            f"{summary.total} problem(s) · {summary.investigating_count} investigating · "
            f"{summary.known_error_count} known error · {summary.fix_planned_count} fix planned · "
            f"{summary.monitoring_count} monitoring · {summary.closed_count} closed · "
            f"{summary.open_occurrences} active occurrences · "
            f"{summary.unassigned_count} unassigned"
        )

    def selected_problem(self) -> GenerationKnownProblem | None:
        rows = self._selected_rows()
        if len(rows) != 1:
            return None
        row = rows[0]
        item = self.table.item(row, 0)
        problem_id = str(item.data(Qt.UserRole) or "") if item is not None else ""
        if not problem_id and 0 <= row < len(self.filtered_problems):
            return self.filtered_problems[row]
        return next(
            (item for item in self.filtered_problems if item.problem_id == problem_id),
            None,
        )

    def _selected_rows(self) -> list[int]:
        rows: set[int] = set()
        model = self.table.selectionModel()
        if model is not None:
            rows.update(index.row() for index in model.selectedRows())
            if not rows:
                rows.update(index.row() for index in model.selectedIndexes())
            current = model.currentIndex()
            if not rows and current.isValid():
                rows.add(current.row())
        if not rows and self.table.currentRow() >= 0:
            rows.add(self.table.currentRow())
        return sorted(row for row in rows if 0 <= row < self.table.rowCount())

    def update_details(self) -> None:
        problem = self.selected_problem()
        if problem is None:
            self.details.clear()
            return
        actions = self.service.list_actions(problem.problem_id)
        action_lines = [
            f"- {item.priority.upper()} · {self._label(item.status)} · "
            f"{item.owner or 'Unassigned'}: {item.title}"
            for item in actions
        ]
        self.details.setPlainText(
            "\n".join(
                [
                    f"Problem: {problem.problem_id}",
                    f"Key: {problem.problem_key}",
                    f"Status / Severity: {self._label(problem.status)} / {self._label(problem.severity)}",
                    f"Owner / Category: {problem.owner or 'Unassigned'} / {self._label(problem.root_cause_category)}",
                    f"Occurrences / Incidents: {problem.occurrence_count} / {len(problem.incident_ids)}",
                    f"First seen: {problem.first_seen_at}",
                    f"Last seen: {problem.last_seen_at}",
                    f"Monitoring until: {problem.monitoring_until or '—'}",
                    f"Fingerprints: {', '.join(problem.fingerprints) or '—'}",
                    f"Incidents: {', '.join(problem.incident_ids) or '—'}",
                    f"Description: {problem.description or '—'}",
                    "",
                    "Workaround:",
                    problem.workaround or "—",
                    "",
                    "Permanent fix:",
                    problem.permanent_fix or "—",
                    "",
                    "Corrective actions:",
                    *(action_lines or ["—"]),
                ]
            )
        )

    def create_from_incidents(self) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Create known problem",
            "Incident IDs (comma or newline separated):",
        )
        if not accepted:
            return
        ids = self._split_ids(text)
        try:
            problem = self.service.create_from_incidents(ids)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self._select_problem(problem.problem_id)
        self.status_label.setText(f"Known problem {problem.problem_id} created or updated.")

    def link_incident(self) -> None:
        problem = self.selected_problem()
        if problem is None:
            self.status_label.setText("Select one known problem.")
            return
        incident_id, accepted = QInputDialog.getText(
            self,
            "Link incident",
            "Incident ID:",
        )
        if not accepted:
            return
        try:
            updated = self.service.link_incident(problem.problem_id, incident_id.strip())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self._select_problem(updated.problem_id)
        self.status_label.setText("Incident linked to known problem.")

    def edit_selected(self) -> None:
        problem = self.selected_problem()
        if problem is None:
            self.status_label.setText("Select one known problem.")
            return
        dialog = KnownProblemEditorDialog(self.service, problem, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.refresh()
        self._select_problem(problem.problem_id)
        self.status_label.setText("Known problem saved.")

    def export_filtered(self) -> tuple[Path, Path] | None:
        if not self.filtered_problems:
            self.status_label.setText("No known problems match the current filters.")
            return None
        paths = self.service.export(
            self.filtered_problems,
            self.export_dir,
            project_name=(
                self.project_name
                if self.project_id is not None and self.current_project_only.isChecked()
                else "all-projects"
            ),
        )
        self.status_label.setText(f"Exported {paths[0].name} and {paths[1].name}")
        return paths

    def _select_problem(self, problem_id: str) -> None:
        for row, problem in enumerate(self.filtered_problems):
            if problem.problem_id == problem_id:
                self.table.selectRow(row)
                return

    @staticmethod
    def _split_ids(value: str) -> list[str]:
        normalized = value.replace(",", "\n").replace(";", "\n")
        return [item.strip() for item in normalized.splitlines() if item.strip()]

    @staticmethod
    def _search_text(problem: GenerationKnownProblem) -> str:
        return " ".join(
            (
                problem.problem_id,
                problem.problem_key,
                problem.title,
                problem.description,
                problem.owner or "",
                problem.root_cause_category,
                problem.workaround,
                problem.permanent_fix,
                *problem.fingerprints,
                *problem.incident_ids,
            )
        ).casefold()

    @staticmethod
    def _label(value: str) -> str:
        return value.replace("_", " ").title()

    @staticmethod
    def _short_timestamp(value: str) -> str:
        return value.replace("T", " ")[:19] if value else "—"
