from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.numeric_spinbox import ControlledDoubleSpinBox, ControlledSpinBox
from app.services.text_source_service import TextSourceEntry, TextSourceService


class TextSourceDialog(QDialog):
    """Text Studio for preparing document and pasted-text generation jobs."""

    def __init__(self, service: TextSourceService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self._all_entries: list[TextSourceEntry] = []
        self.file_paths: list[Path] = []
        self.setObjectName("textStudioDialog")
        self.setWindowTitle("Text Studio")
        self.setMinimumSize(940, 680)
        self.resize(1120, 780)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("textStudioHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel("Text Studio")
        title.setObjectName("dialogTitle")
        helper = QLabel(
            "Turn pasted text, documents, web pages, ebooks and extractable PDFs into reviewed audio jobs. "
            "Nothing is added until the preview is accepted."
        )
        helper.setWordWrap(True)
        helper.setObjectName("dialogDescription")
        header_layout.addWidget(title)
        header_layout.addWidget(helper)
        root.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("textStudioSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._source_panel())
        splitter.addWidget(self._preview_panel())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([430, 650])
        root.addWidget(splitter, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add enabled jobs to project")
        self.buttons.button(QDialogButtonBox.Ok).setIcon(action_icon("project.add_sources"))
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.refresh_preview()

    @property
    def entries(self) -> list[TextSourceEntry]:
        enabled: list[TextSourceEntry] = []
        for row, entry in enumerate(self._all_entries):
            item = self.preview.item(row, 0)
            if item is None or item.checkState() == Qt.Checked:
                enabled.append(entry)
        return enabled

    def _source_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("textStudioSourcePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._manual_tab(), action_icon("general.edit"), "Manual text")
        self.tabs.addTab(self._files_tab(), action_icon("project.add_sources"), "Documents")
        self.tabs.currentChanged.connect(self.refresh_preview)
        layout.addWidget(self.tabs, 1)

        options_box = QFrame()
        options_box.setObjectName("textStudioOptions")
        options = QFormLayout(options_box)
        options.setContentsMargins(10, 10, 10, 10)
        options.setSpacing(8)

        self.split_mode = QComboBox()
        self.split_mode.addItem("One audio file", "single")
        self.split_mode.addItem("Smart chunks", "smart")
        self.split_mode.addItem("One file per paragraph", "paragraphs")
        self.split_mode.addItem("One file per sentence", "sentences")
        self.split_mode.addItem("One file per non-empty line", "lines")
        self.split_mode.setCurrentIndex(1)

        self.max_characters = ControlledSpinBox()
        self.max_characters.setRange(0, 100_000)
        self.max_characters.setValue(1200)
        self.max_characters.setSpecialValueText("No limit")
        self.max_characters.setSuffix(" chars")

        self.filename_prefix = QLineEdit("manual")
        self.filename_prefix.setPlaceholderText("Filename prefix")
        self.start_index = ControlledSpinBox()
        self.start_index.setRange(0, 999_999)
        self.start_index.setValue(1)
        self.output_extension = QComboBox()
        for value in (".mp3", ".wav", ".ogg", ".flac", ".pcm"):
            self.output_extension.addItem(value, value)

        self.characters_per_minute = ControlledSpinBox()
        self.characters_per_minute.setRange(100, 5000)
        self.characters_per_minute.setValue(900)
        self.characters_per_minute.setSuffix(" chars/min")
        self.price_per_million = ControlledDoubleSpinBox()
        self.price_per_million.setRange(0.0, 100_000.0)
        self.price_per_million.setDecimals(2)
        self.price_per_million.setPrefix("$")
        self.price_per_million.setSuffix(" / 1M chars")

        options.addRow("Split strategy", self.split_mode)
        options.addRow("Maximum chunk", self.max_characters)
        options.addRow("Filename prefix", self.filename_prefix)
        options.addRow("Start number", self.start_index)
        options.addRow("Output extension", self.output_extension)
        options.addRow("Speech estimate", self.characters_per_minute)
        options.addRow("Optional cost rate", self.price_per_million)
        layout.addWidget(options_box)

        for signal in (
            self.split_mode.currentIndexChanged,
            self.max_characters.valueChanged,
            self.filename_prefix.textChanged,
            self.start_index.valueChanged,
            self.output_extension.currentIndexChanged,
            self.characters_per_minute.valueChanged,
            self.price_per_million.valueChanged,
        ):
            signal.connect(self.refresh_preview)
        return panel

    def _manual_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        self.manual_text = QTextEdit()
        self.manual_text.setAcceptRichText(False)
        self.manual_text.setPlaceholderText(
            "Type or paste the text that should be converted to speech…\n\n"
            "Use blank lines to separate paragraphs."
        )
        self.manual_text.textChanged.connect(self.refresh_preview)
        layout.addWidget(self.manual_text)
        return page

    def _files_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        actions = QHBoxLayout()
        add = QPushButton("Add documents")
        add.setIcon(action_icon("project.add_sources"))
        remove = QPushButton("Remove selected")
        remove.setIcon(action_icon("general.remove"))
        clear = QPushButton("Clear")
        clear.setIcon(action_icon("general.clear"))
        add.clicked.connect(self._pick_files)
        remove.clicked.connect(self._remove_selected_files)
        clear.clicked.connect(self._clear_files)
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addWidget(clear)
        actions.addStretch()
        layout.addLayout(actions)
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        layout.addWidget(self.file_list)
        note = QLabel(
            "Drop or add TXT, Markdown, RTF, DOCX, HTML, ODT, EPUB and extractable PDF files. "
            "Scanned PDFs require OCR before import."
        )
        note.setWordWrap(True)
        note.setObjectName("formHint")
        layout.addWidget(note)
        return page

    def _preview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("textStudioPreviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search preview…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        all_button = QPushButton("Enable all")
        none_button = QPushButton("Disable all")
        all_button.clicked.connect(lambda: self._set_all_enabled(True))
        none_button.clicked.connect(lambda: self._set_all_enabled(False))
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(all_button)
        toolbar.addWidget(none_button)
        layout.addLayout(toolbar)

        metrics = QFrame()
        metrics.setObjectName("textStudioMetrics")
        metrics_layout = QHBoxLayout(metrics)
        metrics_layout.setContentsMargins(10, 6, 10, 6)
        metrics_layout.setSpacing(14)
        self.jobs_metric = QLabel("Jobs: 0")
        self.characters_metric = QLabel("Characters: 0")
        self.duration_metric = QLabel("Estimated audio: 0s")
        self.cost_metric = QLabel("Estimated cost: —")
        for label in (
            self.jobs_metric,
            self.characters_metric,
            self.duration_metric,
            self.cost_metric,
        ):
            label.setObjectName("textStudioMetric")
            metrics_layout.addWidget(label)
        metrics_layout.addStretch()
        layout.addWidget(metrics)

        self.preview = QTableWidget(0, 4)
        self.preview.setObjectName("textStudioPreview")
        self.preview.setHorizontalHeaderLabels(["Use", "Filename", "Characters", "Text preview"])
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.preview.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview.itemChanged.connect(self._enabled_state_changed)
        layout.addWidget(self.preview, 1)

        self.summary = QLabel("0 enabled jobs")
        self.summary.setObjectName("textSourceSummary")
        layout.addWidget(self.summary)
        return panel

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(url.toLocalFile()).suffix.lower() in self.service.supported_extensions
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self._add_paths([Path(url.toLocalFile()) for url in event.mimeData().urls()])
        self.tabs.setCurrentIndex(1)
        event.acceptProposedAction()

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add text documents",
            str(Path.home()),
            "Text files (*.txt *.text *.md *.markdown *.rtf *.docx *.html *.htm *.odt *.epub *.pdf)",
        )
        self._add_paths([Path(path) for path in paths])

    def _add_paths(self, paths: list[Path]) -> None:
        existing = {str(path.resolve()).casefold() for path in self.file_paths}
        added: list[Path] = []
        for path in paths:
            if path.suffix.lower() not in self.service.supported_extensions:
                continue
            key = str(path.resolve()).casefold()
            if key not in existing:
                self.file_paths.append(path)
                self.file_list.addItem(str(path))
                existing.add(key)
                added.append(path)
        if added and self.filename_prefix.text().strip() in {"", "manual"}:
            self.filename_prefix.setText(added[0].stem if len(added) == 1 else "documents")
        self.refresh_preview()

    def _remove_selected_files(self) -> None:
        rows = sorted({index.row() for index in self.file_list.selectedIndexes()}, reverse=True)
        for row in rows:
            self.file_list.takeItem(row)
            self.file_paths.pop(row)
        self.refresh_preview()

    def _clear_files(self) -> None:
        self.file_paths.clear()
        self.file_list.clear()
        self.refresh_preview()

    def refresh_preview(self) -> None:
        if not hasattr(self, "preview"):
            return
        try:
            split_mode = self.split_mode.currentData() or "single"
            prefix = self.filename_prefix.text().strip() or (
                "manual" if self.tabs.currentIndex() == 0 else "documents"
            )
            extension = self.output_extension.currentData() or ".mp3"
            max_characters = self.max_characters.value()
            if self.tabs.currentIndex() == 0:
                self._all_entries = self.service.entries_from_manual(
                    self.manual_text.toPlainText(),
                    split_mode=split_mode,
                    filename_prefix=prefix,
                    start_index=self.start_index.value(),
                    extension=extension,
                    max_characters=max_characters,
                )
            else:
                file_mode = "file" if split_mode == "single" else split_mode
                self._all_entries = self.service.entries_from_files(
                    self.file_paths,
                    split_mode=file_mode,
                    filename_prefix="" if prefix == "manual" else prefix,
                    start_index=self.start_index.value(),
                    extension=extension,
                    max_characters=max_characters,
                )
            self._render_preview()
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.entries))
        except (OSError, ValueError) as exc:
            self._all_entries = []
            self._render_preview()
            self.summary.setText(str(exc))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    def _render_preview(self) -> None:
        self.preview.blockSignals(True)
        self.preview.setRowCount(len(self._all_entries))
        for row, entry in enumerate(self._all_entries):
            excerpt = " ".join(entry.text.split())
            if len(excerpt) > 220:
                excerpt = f"{excerpt[:217]}…"
            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            enabled.setCheckState(Qt.Checked)
            filename = QTableWidgetItem(entry.filename)
            filename.setToolTip(entry.filename)
            chars = QTableWidgetItem(str(entry.character_count))
            chars.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            preview = QTableWidgetItem(excerpt)
            preview.setToolTip(entry.text)
            self.preview.setItem(row, 0, enabled)
            self.preview.setItem(row, 1, filename)
            self.preview.setItem(row, 2, chars)
            self.preview.setItem(row, 3, preview)
        self.preview.blockSignals(False)
        self._apply_search(self.search.text())
        self._update_metrics()

    def _apply_search(self, query: str) -> None:
        query = query.strip().casefold()
        for row, entry in enumerate(self._all_entries):
            haystack = f"{entry.filename}\n{entry.text}\n{entry.source_label}".casefold()
            self.preview.setRowHidden(row, bool(query) and query not in haystack)

    def _set_all_enabled(self, enabled: bool) -> None:
        self.preview.blockSignals(True)
        for row in range(self.preview.rowCount()):
            item = self.preview.item(row, 0)
            if item is not None and not self.preview.isRowHidden(row):
                item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self.preview.blockSignals(False)
        self._update_metrics()

    def _enabled_state_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._update_metrics()

    def _update_metrics(self) -> None:
        entries = self.entries
        metrics = self.service.metrics(
            entries,
            characters_per_minute=self.characters_per_minute.value(),
            price_per_million_characters=self.price_per_million.value(),
        )
        minutes, seconds = divmod(int(round(metrics.estimated_seconds)), 60)
        duration = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        self.jobs_metric.setText(f"Jobs: {metrics.jobs:,}")
        self.characters_metric.setText(f"Characters: {metrics.characters:,}")
        self.duration_metric.setText(f"Estimated audio: {duration}")
        self.cost_metric.setText(
            f"Estimated cost: ${metrics.estimated_cost:,.2f}"
            if self.price_per_million.value() > 0
            else "Estimated cost: set a rate"
        )
        self.summary.setText(
            f"{metrics.jobs:,} enabled job(s) · {metrics.characters:,} characters"
        )
        if hasattr(self, "buttons"):
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(entries))

    def _accept(self) -> None:
        self.refresh_preview()
        if not self.entries:
            QMessageBox.warning(self, "Text Studio", "Enable at least one non-empty text job.")
            return
        self.accept()

    def source_label(self) -> str:
        if self.tabs.currentIndex() == 0:
            return self.filename_prefix.text().strip() or "manual-text"
        if len(self.file_paths) == 1:
            return self.file_paths[0].stem
        return self.filename_prefix.text().strip() or "text-documents"
