from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.csv_import_state import CsvImportState
from app.services.csv_repair_service import CsvRepairSession


class CsvImportReviewDialog(QDialog):
    def __init__(
        self,
        state: CsvImportState,
        *,
        export_diagnostics: Callable[[], Path],
        generate_repaired_preview: Callable[[], tuple[Path, Path | None]],
        open_source_folder: Callable[[], None],
        save_repaired_csv: Callable[[Path], None] | None = None,
        reports_dir: Path | None = None,
        project_name: str = "No project",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.export_diagnostics = export_diagnostics
        self.generate_repaired_preview = generate_repaired_preview
        self.open_source_folder = open_source_folder
        self.save_repaired_csv_callback = save_repaired_csv
        self.repair_session = CsvRepairSession(state, project_name=project_name) if state.rejected_rows else None
        self.reports_dir = reports_dir
        self.setWindowTitle("CSV import review")
        self.resize(1080, 760)
        self.import_valid_rows = False
        self._repair_index = 0
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.summary = QLabel(
            f"Encoding {self.state.detected_encoding}, delimiter {self._delimiter_label()}, "
            f"{self.state.total_physical_rows:,} physical row(s), {self.state.valid_rows:,} valid, "
            f"{self.state.rejected_rows:,} rejected. Source CSV will not be modified."
        )
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Row", "Severity", "Code", "Filename", "Text excerpt", "Problem"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.table, 1)
        issues = self.state.issues[:300]
        self.table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            values = [
                issue.physical_row or "—",
                issue.severity,
                issue.issue_code,
                issue.parsed_filename,
                issue.parsed_text_excerpt,
                issue.problem,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column in {0, 1}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self._add_repair_workspace(root)
        buttons = QHBoxLayout()
        import_valid = QPushButton("Import valid rows only")
        cancel = QPushButton("Cancel")
        export = QPushButton("Export diagnostics")
        repair = QPushButton("Generate repaired CSV preview")
        open_folder = QPushButton("Open source folder")
        copy = QPushButton("Copy summary")
        import_valid.clicked.connect(self.accept_valid_rows)
        cancel.clicked.connect(self.reject)
        export.clicked.connect(lambda: self.export_diagnostics())
        repair.clicked.connect(lambda: self.generate_repaired_preview())
        open_folder.clicked.connect(self.open_source_folder)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.summary.text()))
        for button in [export, repair, open_folder, copy]:
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(import_valid)
        root.addLayout(buttons)

    def _add_repair_workspace(self, root: QVBoxLayout) -> None:
        if not self.repair_session:
            return
        root.addWidget(QLabel("Repair rejected rows"))
        self.repair_table = QTableWidget(0, 5)
        self.repair_table.setHorizontalHeaderLabels(["Row", "Filename", "Codes", "Validation", "Text"])
        self.repair_table.horizontalHeader().setStretchLastSection(True)
        self.repair_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.repair_table.itemSelectionChanged.connect(self._select_repair_from_table)
        self.repair_table.setMaximumHeight(180)
        root.addWidget(self.repair_table)
        form = QFormLayout()
        self.repair_validation = QLabel("—")
        self.repair_raw = QPlainTextEdit()
        self.repair_raw.setReadOnly(True)
        self.repair_raw.setMaximumHeight(72)
        self.repair_text = QPlainTextEdit()
        self.repair_text.setMaximumHeight(72)
        self.repair_filename = QLineEdit()
        self.repair_filename.textChanged.connect(self._validate_current_repair)
        self.repair_text.textChanged.connect(self._validate_current_repair)
        self.jump_row = QLineEdit()
        self.jump_row.setPlaceholderText("CSV row")
        self.jump_row.returnPressed.connect(self._jump_to_row)
        self.unresolved_only = QCheckBox("Show unresolved only")
        self.unresolved_only.toggled.connect(lambda _checked: self._refresh_repair_table())
        self.template = QLineEdit("{project}-{index:03d}{ext}")
        self.template_ext = QComboBox()
        self.template_ext.addItems([".mp3", ".wav", ".ogg", ".flac"])
        form.addRow("Original raw row", self.repair_raw)
        form.addRow("Text", self.repair_text)
        form.addRow("Filename", self.repair_filename)
        form.addRow("Validation", self.repair_validation)
        form.addRow("Jump to row", self.jump_row)
        form.addRow("Filter", self.unresolved_only)
        form.addRow("Filename template", self.template)
        form.addRow("Template extension", self.template_ext)
        root.addLayout(form)
        actions = QHBoxLayout()
        previous = QPushButton("Previous issue")
        next_issue = QPushButton("Next issue")
        undo = QPushButton("Undo")
        redo = QPushButton("Redo")
        suggest_neighbors = QPushButton("Suggest from neighbors")
        suggest_row = QPushButton("Suggest from row")
        previous_pattern = QPushButton("Previous pattern")
        next_pattern = QPushButton("Next pattern")
        batch = QPushButton("Batch template")
        save_preview = QPushButton("Save repaired preview")
        save_as = QPushButton("Save as new CSV")
        previous.clicked.connect(lambda: self._move_repair(-1))
        next_issue.clicked.connect(lambda: self._move_repair(1))
        undo.clicked.connect(self._undo_repair)
        redo.clicked.connect(self._redo_repair)
        suggest_neighbors.clicked.connect(self._suggest_from_neighbors)
        suggest_row.clicked.connect(self._suggest_from_row)
        previous_pattern.clicked.connect(self._copy_previous_pattern)
        next_pattern.clicked.connect(self._copy_next_pattern)
        batch.clicked.connect(self._batch_apply_template)
        save_preview.clicked.connect(self._save_default_repaired_csv)
        save_as.clicked.connect(self._save_repaired_csv_as)
        for button in [
            previous,
            next_issue,
            undo,
            redo,
            suggest_neighbors,
            suggest_row,
            previous_pattern,
            next_pattern,
            batch,
            save_preview,
            save_as,
        ]:
            actions.addWidget(button)
        actions.addStretch()
        root.addLayout(actions)
        self._refresh_repair_table()
        self._render_repair_issue()

    def _move_repair(self, delta: int) -> None:
        if not self.repair_session or not self.repair_session.repairs:
            return
        repairs = self._visible_repairs()
        if not repairs:
            return
        current = repairs.index(self._current_repair()) if self._current_repair() in repairs else 0
        repair = repairs[(current + delta) % len(repairs)]
        self._repair_index = self.repair_session.repairs.index(repair)
        self._render_repair_issue()

    def _render_repair_issue(self) -> None:
        if not self.repair_session:
            return
        repair = self._current_repair()
        self.repair_raw.setPlainText(repair.raw_row_excerpt)
        self.repair_text.blockSignals(True)
        self.repair_filename.blockSignals(True)
        self.repair_text.setPlainText(repair.text)
        self.repair_filename.setText(repair.filename)
        self.repair_text.blockSignals(False)
        self.repair_filename.blockSignals(False)
        self._set_validation_label(repair)
        self._select_repair_row(repair.physical_row)

    def _validate_current_repair(self) -> None:
        if not self.repair_session:
            return
        repair = self._current_repair()
        try:
            self.repair_session.update_repair(
                repair.physical_row,
                text=self.repair_text.toPlainText(),
                filename=self.repair_filename.text(),
                method="manual",
            )
        except Exception as exc:
            self.repair_validation.setText(str(exc))
        self._set_validation_label(repair)
        self._refresh_repair_table()

    def _suggest_from_neighbors(self) -> None:
        if not self.repair_session:
            return
        repair = self._current_repair()
        filename, pattern = self.repair_session.suggest_from_neighbors(repair.physical_row)
        self.repair_filename.setText(filename)
        self.repair_validation.setText(
            f"Detected prefix {pattern.prefix or '—'}, width {pattern.width or '—'}, extension {pattern.extension}, confidence {pattern.confidence}."
        )

    def _suggest_from_row(self) -> None:
        if self.repair_session:
            self.repair_filename.setText(self.repair_session.suggest_from_row_number(self._current_repair().physical_row, self.template.text()))

    def _copy_previous_pattern(self) -> None:
        if self.repair_session:
            self.repair_filename.setText(self.repair_session.copy_pattern_from_previous(self._current_repair().physical_row))

    def _copy_next_pattern(self) -> None:
        if self.repair_session:
            self.repair_filename.setText(self.repair_session.copy_pattern_from_next(self._current_repair().physical_row))

    def _batch_apply_template(self) -> None:
        if not self.repair_session:
            return
        rows = [repair.physical_row for repair in self._selected_repairs()] or [repair.physical_row for repair in self._visible_repairs()]
        preview = self.repair_session.batch_preview(rows, template=self.template.text(), extension=self.template_ext.currentText())
        conflicts = [row for row in preview if row.conflict]
        if not self._confirm_batch_preview(preview, block=bool(conflicts)):
            return
        self.repair_session.apply_batch(rows, template=self.template.text(), extension=self.template_ext.currentText())
        self._refresh_repair_table()
        self._render_repair_issue()

    def _confirm_batch_preview(self, preview, *, block: bool) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Batch repair preview")
        dialog.resize(860, 420)
        layout = QVBoxLayout(dialog)
        label = QLabel(
            f"{len(preview):,} proposed repair(s). "
            + ("Resolve conflicts before applying." if block else "Source CSV will not be modified.")
        )
        layout.addWidget(label)
        table = QTableWidget(min(len(preview), 300), 4)
        table.setHorizontalHeaderLabels(["Row", "Old filename", "Proposed filename", "Conflict"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for row, preview_row in enumerate(preview[:300]):
            values = [preview_row.physical_row, preview_row.old_filename, preview_row.proposed_filename, preview_row.conflict or "—"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                table.setItem(row, column, item)
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        apply_button = buttons.addButton("Apply fixes", QDialogButtonBox.AcceptRole)
        apply_button.setEnabled(not block)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.Accepted and not block

    def _save_default_repaired_csv(self) -> None:
        if not self.repair_session:
            return
        self._save_repaired_csv(self.state.source_path.with_name(f"{self.state.source_path.stem}.repaired.csv"))

    def _save_repaired_csv_as(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save repaired CSV",
            str(self.state.source_path.with_name(f"{self.state.source_path.stem}.repaired.csv")),
            "CSV files (*.csv)",
        )
        if path:
            self._save_repaired_csv(Path(path))

    def _save_repaired_csv(self, path: Path) -> None:
        if not self.repair_session:
            return
        try:
            result = self.repair_session.save_repaired_csv(path, self.reports_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Save repaired CSV", str(exc))
            return
        self.state.repaired_preview_path = result.repaired_csv_path
        if self.save_repaired_csv_callback and QMessageBox.question(
            self,
            "Replace project CSV reference",
            "Repaired CSV was saved. Replace the current project CSV reference and reload?",
        ) == QMessageBox.Yes:
            self.save_repaired_csv_callback(result.repaired_csv_path)
        QMessageBox.information(
            self,
            "Save repaired CSV",
            f"Saved {result.repaired_csv_path}\nValid rows: {result.diagnostics.valid_rows:,}\nRejected rows: {result.diagnostics.rejected_rows:,}",
        )

    def _undo_repair(self) -> None:
        if self.repair_session and self.repair_session.undo():
            self._refresh_repair_table()
            self._render_repair_issue()

    def _redo_repair(self) -> None:
        if self.repair_session and self.repair_session.redo():
            self._refresh_repair_table()
            self._render_repair_issue()

    def _jump_to_row(self) -> None:
        if not self.repair_session:
            return
        try:
            row_number = int(self.jump_row.text())
        except ValueError:
            return
        for index, repair in enumerate(self.repair_session.repairs):
            if repair.physical_row == row_number:
                self._repair_index = index
                self._render_repair_issue()
                return

    def _refresh_repair_table(self) -> None:
        if not self.repair_session:
            return
        repairs = self._visible_repairs()
        self.repair_table.setRowCount(len(repairs))
        for row, repair in enumerate(repairs):
            values = [
                repair.physical_row,
                repair.filename,
                ", ".join(repair.issue_codes),
                "Valid" if repair.validation.valid else "; ".join(repair.validation.problems),
                repair.text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.repair_table.setItem(row, column, item)

    def _select_repair_from_table(self) -> None:
        if not self.repair_session or not self.repair_table.selectionModel():
            return
        rows = self.repair_table.selectionModel().selectedRows()
        if not rows:
            return
        physical_row = int(self.repair_table.item(rows[0].row(), 0).text())
        for index, repair in enumerate(self.repair_session.repairs):
            if repair.physical_row == physical_row:
                self._repair_index = index
                self._render_repair_issue()
                break

    def _select_repair_row(self, physical_row: int) -> None:
        if not hasattr(self, "repair_table"):
            return
        for row in range(self.repair_table.rowCount()):
            item = self.repair_table.item(row, 0)
            if item and int(item.text()) == physical_row:
                self.repair_table.blockSignals(True)
                self.repair_table.selectRow(row)
                self.repair_table.blockSignals(False)
                break

    def _visible_repairs(self):
        if not self.repair_session:
            return []
        if self.unresolved_only.isChecked():
            return [repair for repair in self.repair_session.repairs if not repair.validation.valid]
        return self.repair_session.repairs

    def _selected_repairs(self):
        if not self.repair_session or not self.repair_table.selectionModel():
            return []
        rows = self.repair_table.selectionModel().selectedRows()
        physical_rows = {int(self.repair_table.item(row.row(), 0).text()) for row in rows}
        return [repair for repair in self.repair_session.repairs if repair.physical_row in physical_rows]

    def _current_repair(self):
        return self.repair_session.repairs[self._repair_index]

    def _set_validation_label(self, repair) -> None:
        if repair.validation.valid:
            self.repair_validation.setText("Valid")
            self.repair_validation.setStyleSheet("color:#22C55E;font-weight:700;")
        else:
            self.repair_validation.setText("; ".join(repair.validation.problems))
            self.repair_validation.setStyleSheet("color:#F59E0B;font-weight:700;")

    def accept_valid_rows(self) -> None:
        self.import_valid_rows = True
        self.accept()

    def _delimiter_label(self) -> str:
        return {"\t": "tab", ",": "comma", ";": "semicolon"}.get(self.state.detected_delimiter, self.state.detected_delimiter)
