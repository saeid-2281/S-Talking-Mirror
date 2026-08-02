from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.numeric_spinbox import ControlledDoubleSpinBox, ControlledSpinBox
from app.gui.widgets.professional_components import InlineFeedbackBar
from app.gui.widgets.text_studio_quality import TextStudioQualityPanel
from app.services.text_source_service import TextSourceEntry, TextSourceService
from app.services.text_studio_quality import (
    TextStudioQualitySummary,
    analyze_text_studio_entries,
    normalize_reading_text,
    renumber_entry_filenames,
    replace_entry_text,
)
from app.services.text_sources import DocumentSection


class ReorderableChunkTable(QTableWidget):
    """QTableWidget with deterministic row-reorder requests.

    The table does not mutate its own data during a drop. It reports the
    selected logical rows and requested target row so the workspace can update
    its entry model and then render once.
    """

    reorder_requested = Signal(object, int)

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event: QDropEvent) -> None:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        if not rows:
            event.ignore()
            return
        target = self.indexAt(event.position().toPoint()).row()
        if target < 0:
            target = self.rowCount()
        self.reorder_requested.emit(rows, target)
        event.acceptProposedAction()


class TextStudioWorkspace(QWidget):
    """Persistent, dock-friendly workspace for preparing text generation jobs."""

    import_requested = Signal(object, str)

    def __init__(
        self,
        service: TextSourceService,
        *,
        session_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.session_path = Path(session_path) if session_path else None
        self.file_paths: list[Path] = []
        self._document_sections: dict[str, list[DocumentSection]] = {}
        self._restored_section_keys: set[str] = set()
        self._entries: list[TextSourceEntry] = []
        self._quality_summary = analyze_text_studio_entries([])
        self._loading = False
        self.setObjectName("textStudioWorkspace")
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QFrame()
        header.setObjectName("textStudioWorkspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        title_box = QVBoxLayout()
        title = QLabel("Text Studio")
        title.setObjectName("workspaceTitle")
        subtitle = QLabel("Prepare, review and edit text chunks before adding them to the generation queue.")
        subtitle.setObjectName("workspaceSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        self.open_session_button = QPushButton("Open session")
        self.open_session_button.setIcon(action_icon("project.open"))
        self.open_session_button.clicked.connect(self.open_session_dialog)
        self.save_session_button = QPushButton("Save session as")
        self.save_session_button.setIcon(action_icon("project.save"))
        self.save_session_button.clicked.connect(self.save_session_as_dialog)
        header_layout.addWidget(self.open_session_button)
        header_layout.addWidget(self.save_session_button)
        self.import_button = QPushButton("Add enabled jobs")
        self.import_button.setIcon(action_icon("project.add_sources"))
        self.import_button.clicked.connect(self._emit_import)
        header_layout.addWidget(self.import_button)
        root.addWidget(header)

        self.quality_panel = TextStudioQualityPanel()
        self.quality_panel.issues_only_changed.connect(lambda _checked: self._apply_search(self.search.text()))
        self.quality_panel.normalize_selected_requested.connect(self.normalize_selected_text)
        self.quality_panel.normalize_all_requested.connect(self.normalize_all_text)
        self.quality_panel.remove_duplicates_requested.connect(self.remove_duplicate_text)
        self.quality_panel.renumber_requested.connect(self.renumber_filenames)
        self.quality_panel.replace_selected_requested.connect(self.replace_selected_text)
        self.quality_panel.replace_all_requested.connect(self.replace_all_text)
        root.addWidget(self.quality_panel)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._sources_panel())
        splitter.addWidget(self._chunks_panel())
        splitter.addWidget(self._editor_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([280, 580, 360])
        root.addWidget(splitter, 1)

        self.metrics = QLabel("0 enabled jobs · 0 characters")
        self.metrics.setObjectName("textStudioWorkspaceMetrics")
        self.feedback = InlineFeedbackBar()
        root.addWidget(self.metrics)
        root.addWidget(self.feedback)

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(500)
        self._autosave.timeout.connect(self.save_session)
        self.load_session()
        self._update_metrics()

    @property
    def entries(self) -> list[TextSourceEntry]:
        result: list[TextSourceEntry] = []
        for row, entry in enumerate(self._entries):
            item = self.chunk_table.item(row, 0)
            if item is None or item.checkState() == Qt.Checked:
                result.append(entry)
        return result

    @property
    def quality_summary(self) -> TextStudioQualitySummary:
        return self._quality_summary

    def _sources_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("textStudioSourcesPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        label = QLabel("Sources")
        label.setObjectName("sectionTitle")
        layout.addWidget(label)

        self.manual_text = QTextEdit()
        self.manual_text.setAcceptRichText(False)
        self.manual_text.setPlaceholderText("Type or paste text here…")
        self.manual_text.textChanged.connect(self._schedule_refresh)
        layout.addWidget(self.manual_text, 1)

        source_actions = QHBoxLayout()
        add_files = QPushButton("Documents")
        add_files.setIcon(action_icon("project.add_sources"))
        add_files.clicked.connect(self._pick_files)
        clear = QPushButton("Clear")
        clear.setIcon(action_icon("general.clear"))
        clear.clicked.connect(self.clear_sources)
        source_actions.addWidget(add_files)
        source_actions.addWidget(clear)
        layout.addLayout(source_actions)

        self.file_list = QTreeWidget()
        self.file_list.setObjectName("textStudioDocumentExplorer")
        self.file_list.setHeaderLabels(["Document / section", "Characters"])
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_list.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_list.itemChanged.connect(self._document_item_changed)
        layout.addWidget(self.file_list, 1)

        section_actions = QHBoxLayout()
        select_all_sections = QPushButton("All sections")
        clear_sections = QPushButton("No sections")
        invert_sections = QPushButton("Invert")
        select_all_sections.clicked.connect(lambda: self.set_all_document_sections(True))
        clear_sections.clicked.connect(lambda: self.set_all_document_sections(False))
        invert_sections.clicked.connect(self.invert_document_sections)
        section_actions.addWidget(select_all_sections)
        section_actions.addWidget(clear_sections)
        section_actions.addWidget(invert_sections)
        layout.addLayout(section_actions)

        remove = QPushButton("Remove selected documents")
        remove.setIcon(action_icon("general.remove"))
        remove.clicked.connect(self._remove_selected_files)
        layout.addWidget(remove)

        options = QFrame()
        options.setObjectName("textStudioWorkspaceOptions")
        form = QFormLayout(options)
        form.setContentsMargins(8, 8, 8, 8)
        self.split_mode = QComboBox()
        for text, value in (
            ("Smart chunks", "smart"),
            ("Whole source", "single"),
            ("Paragraphs", "paragraphs"),
            ("Sentences", "sentences"),
            ("Non-empty lines", "lines"),
        ):
            self.split_mode.addItem(text, value)
        self.max_characters = ControlledSpinBox()
        self.max_characters.setRange(0, 100_000)
        self.max_characters.setValue(1200)
        self.max_characters.setSpecialValueText("No limit")
        self.max_characters.setSuffix(" chars")
        self.prefix = QLineEdit("text-studio")
        self.start_number = ControlledSpinBox()
        self.start_number.setRange(0, 999_999)
        self.start_number.setValue(1)
        self.extension = QComboBox()
        for value in (".mp3", ".wav", ".ogg", ".flac", ".pcm"):
            self.extension.addItem(value, value)
        self.source_label = QLineEdit("Text Studio")
        self.characters_per_minute = ControlledSpinBox()
        self.characters_per_minute.setRange(100, 5000)
        self.characters_per_minute.setValue(900)
        self.characters_per_minute.setSuffix(" chars/min")
        self.price_per_million = ControlledDoubleSpinBox()
        self.price_per_million.setRange(0.0, 100000.0)
        self.price_per_million.setDecimals(2)
        self.price_per_million.setSuffix(" / 1M chars")
        form.addRow("Split", self.split_mode)
        form.addRow("Chunk limit", self.max_characters)
        form.addRow("Filename prefix", self.prefix)
        form.addRow("Start number", self.start_number)
        form.addRow("Output", self.extension)
        form.addRow("Source name", self.source_label)
        form.addRow("Reading speed", self.characters_per_minute)
        form.addRow("Cost rate", self.price_per_million)
        layout.addWidget(options)

        rebuild = QPushButton("Build preview")
        rebuild.setIcon(action_icon("general.refresh"))
        rebuild.clicked.connect(self.rebuild_entries)
        layout.addWidget(rebuild)

        for signal in (
            self.split_mode.currentIndexChanged,
            self.max_characters.valueChanged,
            self.prefix.textChanged,
            self.start_number.valueChanged,
            self.extension.currentIndexChanged,
            self.source_label.textChanged,
            self.characters_per_minute.valueChanged,
            self.price_per_million.valueChanged,
        ):
            signal.connect(self._schedule_session_save)
        return panel

    def _chunks_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("textStudioChunksPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel("Audio jobs")
        title.setObjectName("sectionTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search chunks…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        enable_all = QPushButton("Enable all")
        disable_all = QPushButton("Disable all")
        enable_selected = QPushButton("Enable selected")
        disable_selected = QPushButton("Disable selected")
        enable_all.clicked.connect(lambda: self._set_enabled(True))
        disable_all.clicked.connect(lambda: self._set_enabled(False))
        enable_selected.clicked.connect(lambda: self._set_selected_enabled(True))
        disable_selected.clicked.connect(lambda: self._set_selected_enabled(False))
        toolbar.addWidget(title)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(enable_selected)
        toolbar.addWidget(disable_selected)
        toolbar.addWidget(enable_all)
        toolbar.addWidget(disable_all)
        layout.addLayout(toolbar)

        self.chunk_table = ReorderableChunkTable(0, 3)
        self.chunk_table.setObjectName("textStudioChunkTable")
        self.chunk_table.setHorizontalHeaderLabels(["Use", "Filename", "Characters"])
        self.chunk_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.chunk_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.chunk_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.chunk_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.chunk_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.chunk_table.itemSelectionChanged.connect(self._load_selected_entry)
        self.chunk_table.itemChanged.connect(self._table_item_changed)
        self.chunk_table.reorder_requested.connect(self.reorder_rows)
        layout.addWidget(self.chunk_table, 1)

        actions = QHBoxLayout()
        merge = QPushButton("Merge selected")
        split = QPushButton("Split selected")
        remove = QPushButton("Delete selected")
        merge.clicked.connect(self.merge_selected)
        split.clicked.connect(self.split_selected)
        remove.clicked.connect(self.delete_selected)
        move_up = QPushButton("Move up")
        move_down = QPushButton("Move down")
        move_up.clicked.connect(lambda: self.move_selected(-1))
        move_down.clicked.connect(lambda: self.move_selected(1))
        actions.addWidget(merge)
        actions.addWidget(split)
        actions.addWidget(remove)
        actions.addWidget(move_up)
        actions.addWidget(move_down)
        actions.addStretch(1)
        layout.addLayout(actions)
        return panel

    def _editor_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("textStudioEditorPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        title = QLabel("Chunk editor")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.filename_editor = QLineEdit()
        self.filename_editor.setPlaceholderText("Select a chunk")
        self.filename_editor.editingFinished.connect(self._commit_editor)
        layout.addWidget(self.filename_editor)
        self.text_editor = QTextEdit()
        self.text_editor.setAcceptRichText(False)
        self.text_editor.setPlaceholderText("Select a chunk to review or edit its full text.")
        self.text_editor.textChanged.connect(self._editor_changed)
        layout.addWidget(self.text_editor, 1)
        self.editor_stats = QLabel("No chunk selected")
        self.editor_stats.setObjectName("formHint")
        layout.addWidget(self.editor_stats)
        return panel

    def set_manual_text(self, text: str) -> None:
        self.manual_text.setPlainText(text)
        self.rebuild_entries()

    def _schedule_refresh(self) -> None:
        if self._loading:
            return
        QTimer.singleShot(250, self.rebuild_entries)
        self._schedule_session_save()

    def _schedule_session_save(self) -> None:
        if not self._loading and self.session_path:
            self._autosave.start()

    def _pick_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(self.service.supported_extensions))
        paths, _ = QFileDialog.getOpenFileNames(self, "Add text documents", str(Path.home()), f"Documents ({patterns})")
        self.add_paths([Path(path) for path in paths])

    def add_paths(self, paths: list[Path]) -> None:
        existing = {str(path.resolve()).casefold() for path in self.file_paths}
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in self.service.supported_extensions or not path.is_file():
                continue
            key = str(path.resolve()).casefold()
            if key in existing:
                continue
            existing.add(key)
            self.file_paths.append(path)
            try:
                self._document_sections[key] = self.service.document_sections(path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Text Studio", f"{path.name}: {exc}")
                self.file_paths.pop()
                continue
        self._render_document_tree()
        self.rebuild_entries()
        self._schedule_session_save()

    def clear_sources(self) -> None:
        self._loading = True
        self.manual_text.clear()
        self.file_paths.clear()
        self.file_list.clear()
        self._document_sections.clear()
        self._entries.clear()
        self._loading = False
        self._render_entries()
        self._schedule_session_save()

    def _remove_selected_files(self) -> None:
        selected_paths: set[str] = set()
        for item in self.file_list.selectedItems():
            root = item if item.parent() is None else item.parent()
            selected_paths.add(str(root.data(0, Qt.UserRole) or ""))
        self.file_paths = [path for path in self.file_paths if str(path.resolve()).casefold() not in selected_paths]
        for key in selected_paths:
            self._document_sections.pop(key, None)
        self._render_document_tree()
        self.rebuild_entries()

    def _render_document_tree(self) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for path in self.file_paths:
            key = str(path.resolve()).casefold()
            sections = self._document_sections.get(key, [])
            root = QTreeWidgetItem([path.name, f"{sum(s.character_count for s in sections):,}"])
            root.setData(0, Qt.UserRole, key)
            root.setFlags(root.flags() | Qt.ItemIsUserCheckable)
            root.setCheckState(0, Qt.Checked)
            for section in sections:
                child = QTreeWidgetItem([section.label, f"{section.character_count:,}"])
                child.setData(0, Qt.UserRole, section.selection_key)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                checked = not self._restored_section_keys or section.selection_key in self._restored_section_keys
                child.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                root.addChild(child)
            self.file_list.addTopLevelItem(root)
            root.setExpanded(True)
        self.file_list.blockSignals(False)

    def _document_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._loading:
            return
        self.file_list.blockSignals(True)
        if item.childCount():
            state = item.checkState(0)
            for index in range(item.childCount()):
                item.child(index).setCheckState(0, state)
        elif item.parent() is not None:
            parent = item.parent()
            states = {parent.child(index).checkState(0) for index in range(parent.childCount())}
            parent.setCheckState(0, states.pop() if len(states) == 1 else Qt.PartiallyChecked)
        self.file_list.blockSignals(False)
        self.rebuild_entries()

    def set_all_document_sections(self, enabled: bool) -> None:
        """Enable or disable every selectable document section."""
        self.file_list.blockSignals(True)
        state = Qt.Checked if enabled else Qt.Unchecked
        for root_index in range(self.file_list.topLevelItemCount()):
            root = self.file_list.topLevelItem(root_index)
            root.setCheckState(0, state)
            for child_index in range(root.childCount()):
                root.child(child_index).setCheckState(0, state)
        self.file_list.blockSignals(False)
        self.rebuild_entries()

    def invert_document_sections(self) -> None:
        """Invert all leaf section selections while keeping parent states valid."""
        self.file_list.blockSignals(True)
        for root_index in range(self.file_list.topLevelItemCount()):
            root = self.file_list.topLevelItem(root_index)
            states: set[Qt.CheckState] = set()
            for child_index in range(root.childCount()):
                child = root.child(child_index)
                state = Qt.Unchecked if child.checkState(0) == Qt.Checked else Qt.Checked
                child.setCheckState(0, state)
                states.add(state)
            if states:
                root.setCheckState(0, states.pop() if len(states) == 1 else Qt.PartiallyChecked)
        self.file_list.blockSignals(False)
        self.rebuild_entries()

    def selected_document_sections(self) -> list[DocumentSection]:
        selected: list[DocumentSection] = []
        checked_keys: set[str] = set()
        for index in range(self.file_list.topLevelItemCount()):
            root = self.file_list.topLevelItem(index)
            for child_index in range(root.childCount()):
                child = root.child(child_index)
                if child.checkState(0) == Qt.Checked:
                    checked_keys.add(str(child.data(0, Qt.UserRole)))
        for sections in self._document_sections.values():
            selected.extend(section for section in sections if section.selection_key in checked_keys)
        return selected

    def rebuild_entries(self) -> None:
        if self._loading:
            return
        try:
            mode = self.split_mode.currentData() or "smart"
            prefix = self.prefix.text().strip() or "text-studio"
            start = self.start_number.value()
            extension = self.extension.currentData() or ".mp3"
            limit = self.max_characters.value()
            entries: list[TextSourceEntry] = []
            manual = self.manual_text.toPlainText()
            if manual.strip():
                entries.extend(
                    self.service.entries_from_manual(
                        manual,
                        split_mode=mode,
                        filename_prefix=prefix,
                        start_index=start,
                        extension=extension,
                        max_characters=limit,
                    )
                )
                start += len(entries)
            sections = self.selected_document_sections()
            if sections:
                entries.extend(
                    self.service.entries_from_sections(
                        sections,
                        split_mode="file" if mode == "single" else mode,
                        filename_prefix=prefix,
                        start_index=start,
                        extension=extension,
                        max_characters=limit,
                    )
                )
            self._entries = entries
            self._render_entries()
            self._schedule_session_save()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Text Studio", str(exc))

    def _render_entries(self) -> None:
        selected_ids = {row.row() for row in self.chunk_table.selectionModel().selectedRows()} if self.chunk_table.selectionModel() else set()
        self.chunk_table.blockSignals(True)
        self.chunk_table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            enabled.setCheckState(Qt.Checked)
            filename = QTableWidgetItem(entry.filename)
            characters = QTableWidgetItem(f"{entry.character_count:,}")
            characters.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            characters.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.chunk_table.setItem(row, 0, enabled)
            self.chunk_table.setItem(row, 1, filename)
            self.chunk_table.setItem(row, 2, characters)
        self.chunk_table.blockSignals(False)
        for row in selected_ids:
            if row < self.chunk_table.rowCount():
                self.chunk_table.selectRow(row)
        self._update_metrics()
        self._apply_search(self.search.text())
        self._load_selected_entry()

    def _selected_rows(self) -> list[int]:
        if not self.chunk_table.selectionModel():
            return []
        return sorted({index.row() for index in self.chunk_table.selectionModel().selectedRows()})

    def _load_selected_entry(self) -> None:
        rows = self._selected_rows()
        self._loading = True
        if len(rows) == 1 and rows[0] < len(self._entries):
            entry = self._entries[rows[0]]
            self.filename_editor.setText(entry.filename)
            self.text_editor.setPlainText(entry.text)
            self.editor_stats.setText(f"{entry.character_count:,} characters · {entry.source_label}")
            self.filename_editor.setEnabled(True)
            self.text_editor.setEnabled(True)
        else:
            self.filename_editor.clear()
            self.text_editor.clear()
            self.filename_editor.setEnabled(False)
            self.text_editor.setEnabled(False)
            self.editor_stats.setText("Select one chunk to edit")
        self._loading = False

    def _editor_changed(self) -> None:
        if not self._loading:
            self._commit_editor()

    def _commit_editor(self) -> None:
        rows = self._selected_rows()
        if self._loading or len(rows) != 1:
            return
        row = rows[0]
        if row >= len(self._entries):
            return
        old = self._entries[row]
        text = self.text_editor.toPlainText().strip()
        filename = self.filename_editor.text().strip() or old.filename
        if not text:
            return
        self._entries[row] = TextSourceEntry(text=text, filename=filename, source_label=old.source_label)
        self.chunk_table.blockSignals(True)
        self.chunk_table.item(row, 1).setText(filename)
        self.chunk_table.item(row, 2).setText(f"{len(text):,}")
        self.chunk_table.blockSignals(False)
        self.editor_stats.setText(f"{len(text):,} characters · {old.source_label}")
        self._update_metrics()
        self._schedule_session_save()

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if item.column() == 1 and row < len(self._entries):
            old = self._entries[row]
            self._entries[row] = TextSourceEntry(old.text, item.text().strip() or old.filename, old.source_label)
        self._update_metrics()
        self._schedule_session_save()

    def merge_selected(self) -> None:
        rows = self._selected_rows()
        if len(rows) < 2:
            return
        first = rows[0]
        entries = [self._entries[row] for row in rows]
        merged = TextSourceEntry(
            text="\n\n".join(entry.text for entry in entries),
            filename=entries[0].filename,
            source_label=entries[0].source_label,
        )
        for row in reversed(rows):
            self._entries.pop(row)
        self._entries.insert(first, merged)
        self._render_entries()
        self.chunk_table.selectRow(first)
        self._schedule_session_save()

    def split_selected(self) -> None:
        """Split every selected chunk using the current smart chunk limit."""
        rows = self._selected_rows()
        if not rows:
            return
        first_changed: int | None = None
        for row in reversed(rows):
            entry = self._entries[row]
            chunks = self.service.split_text(
                entry.text,
                "smart",
                max_characters=self.max_characters.value() or 1200,
            )
            if len(chunks) <= 1:
                continue
            stem = Path(entry.filename).stem
            suffix = Path(entry.filename).suffix or (self.extension.currentData() or ".mp3")
            replacements = [
                TextSourceEntry(chunk, f"{stem}-{index:03d}{suffix}", entry.source_label)
                for index, chunk in enumerate(chunks, 1)
            ]
            self._entries[row : row + 1] = replacements
            first_changed = row if first_changed is None else min(first_changed, row)
        if first_changed is None:
            return
        self._render_entries()
        self.chunk_table.selectRow(first_changed)
        self._schedule_session_save()

    def _enabled_states(self) -> list[bool]:
        return [
            bool(self.chunk_table.item(row, 0))
            and self.chunk_table.item(row, 0).checkState() == Qt.Checked
            for row in range(self.chunk_table.rowCount())
        ]

    def _restore_enabled_states(self, states: list[bool]) -> None:
        self.chunk_table.blockSignals(True)
        for row, checked in enumerate(states[: self.chunk_table.rowCount()]):
            item = self.chunk_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.chunk_table.blockSignals(False)

    def reorder_rows(self, rows: object, target_row: int) -> None:
        """Move one or more selected rows to a drop target, preserving state."""
        selected = sorted({int(row) for row in rows if 0 <= int(row) < len(self._entries)})
        if not selected:
            return
        entries = list(self._entries)
        enabled = self._enabled_states()
        moved_entries = [entries[row] for row in selected]
        moved_enabled = [enabled[row] for row in selected]
        for row in reversed(selected):
            entries.pop(row)
            enabled.pop(row)
        adjusted_target = int(target_row) - sum(row < int(target_row) for row in selected)
        adjusted_target = max(0, min(adjusted_target, len(entries)))
        entries[adjusted_target:adjusted_target] = moved_entries
        enabled[adjusted_target:adjusted_target] = moved_enabled
        self._entries = entries
        self._render_entries()
        self._restore_enabled_states(enabled)
        self.chunk_table.clearSelection()
        for row in range(adjusted_target, adjusted_target + len(moved_entries)):
            self.chunk_table.selectRow(row)
        self._update_metrics()
        self._schedule_session_save()

    def move_selected(self, direction: int) -> None:
        rows = self._selected_rows()
        if len(rows) != 1 or direction not in {-1, 1}:
            return
        row = rows[0]
        target = row + direction
        if not 0 <= target < len(self._entries):
            return
        enabled = self._enabled_states()
        self._entries[row], self._entries[target] = self._entries[target], self._entries[row]
        enabled[row], enabled[target] = enabled[target], enabled[row]
        self._render_entries()
        self._restore_enabled_states(enabled)
        self.chunk_table.selectRow(target)
        self._update_metrics()
        self._schedule_session_save()

    def delete_selected(self) -> None:
        for row in reversed(self._selected_rows()):
            self._entries.pop(row)
        self._render_entries()
        self._schedule_session_save()

    def _set_enabled(self, enabled: bool) -> None:
        self.chunk_table.blockSignals(True)
        for row in range(self.chunk_table.rowCount()):
            if self.chunk_table.isRowHidden(row):
                continue
            item = self.chunk_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self.chunk_table.blockSignals(False)
        self._update_metrics()
        self._schedule_session_save()

    def _set_selected_enabled(self, enabled: bool) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        self.chunk_table.blockSignals(True)
        for row in rows:
            item = self.chunk_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self.chunk_table.blockSignals(False)
        self._update_metrics()
        self._schedule_session_save()

    def _apply_search(self, query: str) -> None:
        query = str(query or "").strip().casefold()
        issue_rows = self._quality_summary.issue_rows
        issues_only = self.quality_panel.issues_only.isChecked()
        for row, entry in enumerate(self._entries):
            haystack = f"{entry.filename}\n{entry.text}\n{entry.source_label}".casefold()
            query_mismatch = bool(query) and query not in haystack
            issue_mismatch = issues_only and row not in issue_rows
            self.chunk_table.setRowHidden(row, query_mismatch or issue_mismatch)

    def _replace_entries_preserving_state(
        self,
        entries: list[TextSourceEntry],
        states: list[bool],
        *,
        selected_rows: list[int] | None = None,
    ) -> None:
        self._entries = entries
        self._render_entries()
        self._restore_enabled_states(states)
        self.chunk_table.clearSelection()
        for row in selected_rows or []:
            if 0 <= row < self.chunk_table.rowCount():
                self.chunk_table.selectRow(row)
        self._update_metrics()
        self._apply_search(self.search.text())
        self._schedule_session_save()

    def normalize_selected_text(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self.feedback.show_message("Select one or more jobs to normalize.", tone="warning")
            return
        states = self._enabled_states()
        updated = list(self._entries)
        changed = 0
        for row in rows:
            entry = updated[row]
            text = normalize_reading_text(entry.text)
            if text and text != entry.text:
                updated[row] = TextSourceEntry(text, entry.filename, entry.source_label)
                changed += 1
        self._replace_entries_preserving_state(updated, states, selected_rows=rows)
        self.feedback.show_message(
            f"Normalized whitespace in {changed:,} selected job(s).",
            tone="success" if changed else "info",
        )

    def normalize_all_text(self) -> None:
        states = self._enabled_states()
        updated: list[TextSourceEntry] = []
        changed = 0
        for entry in self._entries:
            text = normalize_reading_text(entry.text)
            if text and text != entry.text:
                changed += 1
                updated.append(TextSourceEntry(text, entry.filename, entry.source_label))
            else:
                updated.append(entry)
        self._replace_entries_preserving_state(updated, states)
        self.feedback.show_message(
            f"Normalized whitespace in {changed:,} job(s).",
            tone="success" if changed else "info",
        )

    def remove_duplicate_text(self) -> None:
        states = self._enabled_states()
        seen: set[str] = set()
        keep_entries: list[TextSourceEntry] = []
        keep_states: list[bool] = []
        removed = 0
        for row, entry in enumerate(self._entries):
            key = " ".join(entry.text.split()).casefold()
            enabled = states[row] if row < len(states) else True
            if enabled and key and key in seen:
                removed += 1
                continue
            if enabled and key:
                seen.add(key)
            keep_entries.append(entry)
            keep_states.append(enabled)
        self._replace_entries_preserving_state(keep_entries, keep_states)
        self.feedback.show_message(
            f"Removed {removed:,} duplicate enabled job(s).",
            tone="success" if removed else "info",
        )

    def renumber_filenames(self) -> None:
        states = self._enabled_states()
        updated = renumber_entry_filenames(
            self._entries,
            prefix=self.prefix.text().strip() or "text-studio",
            start_index=self.start_number.value(),
            extension=self.extension.currentData() or ".mp3",
        )
        self._replace_entries_preserving_state(updated, states)
        self.feedback.show_message(f"Renumbered {len(updated):,} filename(s).", tone="success")

    def replace_selected_text(self, find_text: str, replacement: str, case_sensitive: bool) -> None:
        rows = self._selected_rows()
        if not rows:
            self.feedback.show_message("Select one or more jobs before replacing text.", tone="warning")
            return
        states = self._enabled_states()
        updated, count = replace_entry_text(
            self._entries,
            find_text=find_text,
            replacement=replacement,
            rows=rows,
            case_sensitive=case_sensitive,
        )
        self._replace_entries_preserving_state(updated, states, selected_rows=rows)
        self.feedback.show_message(
            f"Replaced {count:,} occurrence(s) in selected jobs.",
            tone="success" if count else "info",
        )

    def replace_all_text(self, find_text: str, replacement: str, case_sensitive: bool) -> None:
        states = self._enabled_states()
        updated, count = replace_entry_text(
            self._entries,
            find_text=find_text,
            replacement=replacement,
            case_sensitive=case_sensitive,
        )
        self._replace_entries_preserving_state(updated, states)
        self.feedback.show_message(
            f"Replaced {count:,} occurrence(s) across all jobs.",
            tone="success" if count else "info",
        )

    def _annotate_quality_issues(self) -> None:
        by_row: dict[int, list[str]] = {}
        for issue in self._quality_summary.issues:
            by_row.setdefault(issue.row, []).append(issue.message)
        # Tooltip and metadata are presentation-only. QTableWidgetItem changes
        # emit itemChanged, whose handler recalculates the quality summary.
        # Blocking the table signals here prevents issue rows from recursively
        # re-entering _update_metrics() while their annotations are refreshed.
        previous = self.chunk_table.blockSignals(True)
        try:
            for row in range(self.chunk_table.rowCount()):
                messages = tuple(by_row.get(row, []))
                tooltip = "\n".join(messages) or "Preparation checks passed."
                for column in (1, 2):
                    item = self.chunk_table.item(row, column)
                    if item is not None:
                        item.setToolTip(tooltip)
                        item.setData(Qt.UserRole + 20, messages)
        finally:
            self.chunk_table.blockSignals(previous)

    def _update_metrics(self) -> None:
        metrics = self.service.metrics(
            self.entries,
            characters_per_minute=self.characters_per_minute.value(),
            price_per_million_characters=self.price_per_million.value(),
        )
        self._quality_summary = analyze_text_studio_entries(
            self._entries,
            enabled=self._enabled_states(),
            max_characters=self.max_characters.value(),
        )
        self.quality_panel.set_summary(self._quality_summary)
        self._annotate_quality_issues()
        minutes, seconds = divmod(int(round(metrics.estimated_seconds)), 60)
        duration = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        cost = f" · estimated cost {metrics.estimated_cost:,.2f}" if self.price_per_million.value() > 0 else ""
        self.metrics.setText(
            f"{metrics.jobs:,} enabled jobs · {metrics.characters:,} characters · estimated audio {duration}{cost}"
        )
        self.import_button.setEnabled(self._quality_summary.ready_for_import)
        self.import_button.setToolTip(
            "Add all enabled jobs to the generation queue"
            if self._quality_summary.ready_for_import
            else self._quality_summary.status_text
        )

    def _emit_import(self) -> None:
        entries = self.entries
        if not entries or not self._quality_summary.ready_for_import:
            self.feedback.show_message(self._quality_summary.status_text, tone=self._quality_summary.tone)
            return
        self.import_requested.emit(entries, self.source_label.text().strip() or "Text Studio")
        self.feedback.show_message(f"Prepared {len(entries):,} job(s) for queue import.", tone="success")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(url.toLocalFile()).suffix.lower() in self.service.supported_extensions
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.add_paths([Path(url.toLocalFile()) for url in event.mimeData().urls()])
        event.acceptProposedAction()

    def session_payload(self) -> dict[str, object]:
        """Return the complete portable Text Studio session payload."""
        return {
            "version": 3,
            "manual_text": self.manual_text.toPlainText(),
            "file_paths": [str(path) for path in self.file_paths],
            "split_mode": self.split_mode.currentData(),
            "max_characters": self.max_characters.value(),
            "prefix": self.prefix.text(),
            "start_number": self.start_number.value(),
            "extension": self.extension.currentData(),
            "source_label": self.source_label.text(),
            "characters_per_minute": self.characters_per_minute.value(),
            "price_per_million": self.price_per_million.value(),
            "selected_sections": [section.selection_key for section in self.selected_document_sections()],
            "entries": [asdict(entry) for entry in self._entries],
            "enabled": self._enabled_states(),
        }

    @staticmethod
    def _write_session_payload(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def export_session(self, path: Path) -> Path:
        destination = Path(path)
        self._write_session_payload(destination, self.session_payload())
        return destination

    def import_session(self, path: Path, *, adopt_path: bool = False) -> bool:
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            self._apply_session_payload(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        if adopt_path:
            self.session_path = source
        return True

    def open_session_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Text Studio session",
            str(self.session_path.parent if self.session_path else Path.home()),
            "Text Studio session (*.json);;JSON files (*.json)",
        )
        if path and not self.import_session(Path(path)):
            QMessageBox.warning(self, "Text Studio", "The selected session could not be opened.")

    def save_session_as_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Text Studio session",
            str(self.session_path or (Path.home() / "text-studio-session.json")),
            "Text Studio session (*.json)",
        )
        if path:
            destination = Path(path)
            if not destination.suffix:
                destination = destination.with_suffix(".json")
            self.export_session(destination)

    def _apply_session_payload(self, payload: dict[str, object]) -> None:
        if payload.get("version") not in {1, 2, 3}:
            raise ValueError("Unsupported Text Studio session version.")
        self._loading = True
        try:
            self.manual_text.setPlainText(str(payload.get("manual_text", "")))
            self.file_paths = [Path(value) for value in payload.get("file_paths", []) if Path(value).is_file()]
            self._restored_section_keys = {str(value) for value in payload.get("selected_sections", [])}
            self._document_sections = {}
            for path in self.file_paths:
                key = str(path.resolve()).casefold()
                try:
                    self._document_sections[key] = self.service.document_sections(path)
                except (OSError, ValueError):
                    self._document_sections[key] = []
            self._render_document_tree()
            self._set_combo_data(self.split_mode, payload.get("split_mode", "smart"))
            self.max_characters.setValue(int(payload.get("max_characters", 1200)))
            self.prefix.setText(str(payload.get("prefix", "text-studio")))
            self.start_number.setValue(int(payload.get("start_number", 1)))
            self._set_combo_data(self.extension, payload.get("extension", ".mp3"))
            self.source_label.setText(str(payload.get("source_label", "Text Studio")))
            self.characters_per_minute.setValue(int(payload.get("characters_per_minute", 900)))
            self.price_per_million.setValue(float(payload.get("price_per_million", 0.0)))
            self._entries = [TextSourceEntry(**item) for item in payload.get("entries", [])]
            enabled = [bool(value) for value in payload.get("enabled", [])]
        finally:
            self._loading = False
        self._render_entries()
        self._restore_enabled_states(enabled)
        self._update_metrics()

    def save_session(self) -> None:
        if not self.session_path or self._loading:
            return
        self._write_session_payload(self.session_path, self.session_payload())

    def load_session(self) -> None:
        if not self.session_path or not self.session_path.exists():
            return
        self.import_session(self.session_path)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
