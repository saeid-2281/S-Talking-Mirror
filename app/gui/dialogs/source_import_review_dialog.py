from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.project_source import SourceCollectionImportResult, SourceImportResult


class SourceImportReviewDialog(QDialog):
    def __init__(
        self,
        result: SourceCollectionImportResult,
        parent: QWidget | None = None,
        *,
        current_queue_jobs: int = 0,
        current_source_count: int = 0,
    ) -> None:
        super().__init__(parent)
        self.import_result = result
        self.current_queue_jobs = max(0, int(current_queue_jobs))
        self.current_source_count = max(0, int(current_source_count))
        self.selected_mode = "selected"
        self.setObjectName("sourceImportReviewDialog")
        self.setWindowTitle("Source Import Review")
        self.resize(1040, 680)
        self.setMinimumSize(720, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.workspace = DialogWorkspace(
            "Source import review",
            "Validate mappings, row counts and collisions before creating generation jobs.",
            icon_name="project.add_sources",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.summary_card = DialogStatusCard("Import summary", self._summary_text(), tone="info")
        self.summary_card.setObjectName("sourceImportSummaryCard")
        self.summary = self.summary_card.detail_label
        self.workspace.add_body_widget(self.summary_card)

        self.handoff_card = DialogStatusCard(
            "Queue handoff",
            self._handoff_text(),
            tone="info",
        )
        self.handoff_card.setObjectName("sourceImportQueueHandoffCard")
        self.workspace.add_body_widget(self.handoff_card)

        table_section = DialogSection(
            "Sources and mappings",
            "Use horizontal scrolling for detailed mapping columns. Select one or more rows before applying source-specific actions.",
        )
        self.table = QTableWidget(0, 13)
        self.table.setObjectName("sourceImportTable")
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
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setMinimumHeight(280)
        self.table.itemSelectionChanged.connect(self._update_import_actions)
        table_section.add_widget(self.table, 1)
        self.workspace.add_body_widget(table_section, 1)

        tools_section = DialogSection(
            "Selected-source tools",
            "These actions affect only selected source rows and do not import jobs until an Import action is confirmed.",
        )
        tools = QGridLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setHorizontalSpacing(8)
        tools.setVerticalSpacing(8)
        tool_specs = [
            ("Enable / disable", self.toggle_selected, "general.settings"),
            ("Remove source", self.remove_selected, "general.remove"),
            ("Reconfigure mapping", self.reconfigure_selected, "general.edit"),
            ("Export diagnostics", self.export_diagnostics, "report"),
        ]
        self.tool_buttons: list[QPushButton] = []
        for index, (text, handler, icon_name) in enumerate(tool_specs):
            button = QPushButton(text)
            button.setObjectName("sourceImportToolAction")
            button.setIcon(action_icon(icon_name))
            button.setMinimumHeight(34)
            button.clicked.connect(handler)
            tools.addWidget(button, index // 2, index % 2)
            self.tool_buttons.append(button)
        tools.setColumnStretch(0, 1)
        tools.setColumnStretch(1, 1)
        tools_section.add_layout(tools)
        self.workspace.add_body_widget(tools_section)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.import_all_button = QPushButton("Import all valid")
        self.import_all_button.clicked.connect(self.import_all_valid)
        self.import_selected_button = QPushButton("Import selected")
        self.import_selected_button.setObjectName("dialogPrimaryAction")
        self.import_selected_button.setIcon(action_icon("project.add_sources"))
        self.import_selected_button.clicked.connect(self.import_selected)
        self.workspace.add_footer_stretch()
        self.workspace.add_footer_widget(self.cancel_button)
        self.workspace.add_footer_widget(self.import_all_button)
        self.workspace.add_footer_widget(self.import_selected_button)

        self.render()

    def importable_results(self) -> list[SourceImportResult]:
        if self.selected_mode == "all":
            return [item for item in self.import_result.sources if item.can_import]
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [item for row, item in enumerate(self.import_result.sources) if row in selected and item.can_import]

    def import_selected(self) -> None:
        if not self._selected_importable_results():
            return
        self.selected_mode = "selected"
        self.accept()

    def import_all_valid(self) -> None:
        if not any(item.can_import for item in self.import_result.sources):
            return
        self.selected_mode = "all"
        self.accept()

    def _selected_importable_results(self) -> list[SourceImportResult]:
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [
            item
            for row, item in enumerate(self.import_result.sources)
            if row in selected and item.can_import
        ]

    def _selected_importable_job_count(self) -> int:
        return sum(len(item.jobs) for item in self._selected_importable_results())

    def _update_import_actions(self) -> None:
        all_valid = [item for item in self.import_result.sources if item.can_import]
        selected = self._selected_importable_results()
        selected_jobs = sum(len(item.jobs) for item in selected)
        all_jobs = sum(len(item.jobs) for item in all_valid)

        self.import_all_button.setEnabled(bool(all_valid))
        self.import_selected_button.setEnabled(bool(selected))
        self.import_selected_button.setToolTip(
            (
                f"Import {selected_jobs:,} job(s) from {len(selected):,} selected valid source(s)"
                if selected
                else "Select at least one valid source before importing selected rows"
            )
        )
        self.import_all_button.setToolTip(
            (
                f"Import {all_jobs:,} job(s) from all {len(all_valid):,} valid source(s)"
                if all_valid
                else "No valid sources are available to import"
            )
        )
        self.handoff_card.update_status(
            "Queue handoff",
            self._handoff_text(
                selected_sources=len(selected),
                selected_jobs=selected_jobs,
                all_sources=len(all_valid),
                all_jobs=all_jobs,
            ),
            tone="warning" if self.current_queue_jobs else "info",
        )

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
        rejected = sum(item.source.rejected_rows for item in self.import_result.sources)
        collisions = len(self.import_result.collisions)
        tone = "error" if collisions else ("warning" if rejected else "success")
        self.summary_card.update_status("Import summary", self._summary_text(), tone=tone)
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
        self._update_import_actions()

    def _handoff_text(
        self,
        *,
        selected_sources: int = 0,
        selected_jobs: int = 0,
        all_sources: int | None = None,
        all_jobs: int | None = None,
    ) -> str:
        valid_sources = (
            sum(1 for item in self.import_result.sources if item.can_import)
            if all_sources is None
            else all_sources
        )
        valid_jobs = (
            sum(len(item.jobs) for item in self.import_result.sources if item.can_import)
            if all_jobs is None
            else all_jobs
        )
        queue_text = (
            f"Current queue has {self.current_queue_jobs:,} job(s) and will be rebuilt after confirmation."
            if self.current_queue_jobs
            else "Current queue is empty; confirmed source rows will create the prepared queue."
        )
        selected_text = (
            f" Selected now: {selected_sources:,} valid source(s) / {selected_jobs:,} job(s)."
            if selected_sources
            else " Select at least one valid source for Import selected, or use Import all valid."
        )
        return (
            f"{queue_text} Review contains {valid_sources:,} valid source(s) / {valid_jobs:,} importable job(s)."
            f"{selected_text} A confirmed import invalidates the existing Preflight result; "
            "Preflight is NOT run automatically and generation is NOT started."
        )

    def _summary_text(self) -> str:
        valid = sum(len(item.jobs) for item in self.import_result.sources if item.can_import)
        rejected = sum(item.source.rejected_rows for item in self.import_result.sources)
        collisions = len(self.import_result.collisions)
        return f"{len(self.import_result.sources):,} source(s) · {valid:,} importable row(s) · {rejected:,} rejected row(s) · {collisions:,} collision(s). Jobs are created only after import."


class SourceMappingDialog(QDialog):
    def __init__(self, result: SourceImportResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = result
        self.setObjectName("sourceMappingDialog")
        self.setWindowTitle("Reconfigure source mapping")
        self.resize(620, 500)
        self.setMinimumSize(480, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Reconfigure source mapping",
            "Map source columns to the text, filename and optional provider override fields.",
            icon_name="general.edit",
            parent=self,
        )
        root.addWidget(self.workspace)

        section = DialogSection(
            result.source.display_name,
            "Text and filename are required. Voice, model and language mappings are optional.",
        )
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
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
            form.addRow(label, widget)
        section.add_layout(form)
        self.workspace.add_body_widget(section)
        self.workspace.add_body_stretch()

        cancel = QPushButton("Cancel")
        apply_button = QPushButton("Apply mapping")
        apply_button.setObjectName("dialogPrimaryAction")
        apply_button.clicked.connect(self.apply)
        cancel.clicked.connect(self.reject)
        self.workspace.add_footer_stretch()
        self.workspace.add_footer_widget(cancel)
        self.workspace.add_footer_widget(apply_button)

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
