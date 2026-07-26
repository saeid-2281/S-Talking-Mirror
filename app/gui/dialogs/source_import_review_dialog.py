from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.project_source import SourceCollectionImportResult, SourceImportResult


class SourceImportReviewDialog(QDialog):
    def __init__(self, result: SourceCollectionImportResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.import_result = result
        self.selected_mode = "selected"
        self.setWindowTitle("Source Import Review")
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        self.summary = QLabel(self._summary_text())
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 13)
        self.table.setHorizontalHeaderLabels(
            [
                "Enabled",
                "Source",
                "Type",
                "Worksheet",
                "Columns",
                "Text",
                "Filename",
                "Voice",
                "Model",
                "Language",
                "Rows",
                "Valid",
                "Status",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.table, 1)
        self.render()
        buttons = QHBoxLayout()
        for text, handler in [
            ("Import selected", self.import_selected),
            ("Import all valid", self.import_all_valid),
            ("Enable/disable source", self.toggle_selected),
            ("Remove source", self.remove_selected),
            ("Reconfigure mapping", self.reconfigure_selected),
            ("Export diagnostics", self.export_diagnostics),
            ("Cancel", self.reject),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def importable_results(self) -> list[SourceImportResult]:
        if self.selected_mode == "all":
            return [item for item in self.import_result.sources if item.can_import]
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [item for row, item in enumerate(self.import_result.sources) if row in selected and item.can_import]

    def import_selected(self) -> None:
        self.selected_mode = "selected"
        self.accept()

    def import_all_valid(self) -> None:
        self.selected_mode = "all"
        self.accept()

    def toggle_selected(self) -> None:
        for index in self.table.selectionModel().selectedRows():
            source = self.import_result.sources[index.row()].source
            source.enabled = not source.enabled
        self.render()

    def remove_selected(self) -> None:
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        self.import_result.sources[:] = [item for row, item in enumerate(self.import_result.sources) if row not in selected]
        self.render()

    def reconfigure_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.import_result.sources[row]
        dialog = SourceMappingDialog(item, self)
        if dialog.exec() == QDialog.Accepted:
            self.render()

    def export_diagnostics(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export source diagnostics", "source-import-diagnostics.json", "JSON (*.json)")
        if not path:
            return
        payload = {
            "sources": [
                {
                    "source_id": item.source.source_id,
                    "path": str(item.source.source_path),
                    "worksheet": item.source.worksheet_name,
                    "headers": item.headers,
                    "row_count": item.row_count,
                    "valid_rows": len(item.jobs),
                    "issues": [issue.__dict__ for issue in item.issues],
                }
                for item in self.import_result.sources
            ],
            "collisions": [issue.__dict__ for issue in self.import_result.collisions],
        }
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def render(self) -> None:
        self.summary.setText(self._summary_text())
        self.table.setRowCount(len(self.import_result.sources))
        for row, item in enumerate(self.import_result.sources):
            source = item.source
            columns = ", ".join(item.headers)
            values = [
                "Yes" if source.enabled else "No",
                source.display_name,
                source.source_type.value,
                source.worksheet_name or "-",
                columns,
                source.mapping.text_column,
                source.mapping.filename_column,
                source.mapping.voice_column or "-",
                source.mapping.model_column or "-",
                source.mapping.language_column or "-",
                item.row_count,
                len(item.jobs),
                source.import_status.value,
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                table_item.setToolTip(str(source.source_path) if column in {1, 3} else str(value))
                self.table.setItem(row, column, table_item)
        self.table.resizeColumnsToContents()

    def _summary_text(self) -> str:
        valid = sum(len(item.jobs) for item in self.import_result.sources if item.can_import)
        rejected = sum(item.source.rejected_rows for item in self.import_result.sources)
        collisions = len(self.import_result.collisions)
        return f"{len(self.import_result.sources):,} source(s), {valid:,} importable rows, {rejected:,} rejected rows, {collisions:,} collision(s). Jobs are created only after import."


class SourceMappingDialog(QDialog):
    def __init__(self, result: SourceImportResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Reconfigure source mapping")
        layout = QVBoxLayout(self)
        self.text_column = self._combo(result.source.mapping.text_column)
        self.filename_column = self._combo(result.source.mapping.filename_column)
        self.voice_column = self._combo(result.source.mapping.voice_column, optional=True)
        self.model_column = self._combo(result.source.mapping.model_column, optional=True)
        self.language_column = self._combo(result.source.mapping.language_column, optional=True)
        for label, widget in [
            ("Text column", self.text_column),
            ("Filename column", self.filename_column),
            ("Voice column", self.voice_column),
            ("Model column", self.model_column),
            ("Language column", self.language_column),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(widget, 1)
            layout.addLayout(row)
        buttons = QHBoxLayout()
        apply_button = QPushButton("Apply")
        cancel = QPushButton("Cancel")
        apply_button.clicked.connect(self.apply)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(apply_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _combo(self, current: str | None, *, optional: bool = False) -> QComboBox:
        combo = QComboBox()
        if optional:
            combo.addItem("-", None)
        for header in self.result.headers:
            combo.addItem(header, header)
        if current:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        return combo

    def apply(self) -> None:
        from app.models.project_source import SourceColumnMapping

        self.result.source.mapping = SourceColumnMapping(
            text_column=self.text_column.currentData() or "text",
            filename_column=self.filename_column.currentData() or "filename",
            voice_column=self.voice_column.currentData(),
            model_column=self.model_column.currentData(),
            language_column=self.language_column.currentData(),
        )
        self.accept()
