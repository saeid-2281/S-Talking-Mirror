from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.services.text_source_service import TextSourceEntry, TextSourceService


class TextSourceDialog(QDialog):
    """Creates queue-ready rows from pasted text or common text documents."""

    def __init__(self, service: TextSourceService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.entries: list[TextSourceEntry] = []
        self.file_paths: list[Path] = []
        self.setWindowTitle("Add text source")
        self.setMinimumSize(820, 620)
        self.resize(940, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Create audio jobs from text")
        title.setObjectName("dialogTitle")
        helper = QLabel(
            "Paste text manually or add TXT, Markdown, RTF, DOCX, HTML and ODT documents. "
            "Review the generated filenames and character counts before adding them to the project."
        )
        helper.setWordWrap(True)
        helper.setObjectName("dialogDescription")
        root.addWidget(title)
        root.addWidget(helper)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._manual_tab(), action_icon("general.edit"), "Manual text")
        self.tabs.addTab(self._files_tab(), action_icon("project.add_sources"), "Text files")
        self.tabs.currentChanged.connect(self.refresh_preview)
        root.addWidget(self.tabs, 2)

        options = QWidget()
        options_layout = QFormLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        self.split_mode = QComboBox()
        self.split_mode.addItem("One audio file", "single")
        self.split_mode.addItem("One file per paragraph", "paragraphs")
        self.split_mode.addItem("One file per non-empty line", "lines")
        self.split_mode.addItem("One file per sentence", "sentences")
        self.filename_prefix = QLineEdit("manual")
        self.filename_prefix.setPlaceholderText("Filename prefix")
        self.start_index = QSpinBox()
        self.start_index.setRange(0, 999999)
        self.start_index.setValue(1)
        self.output_extension = QComboBox()
        for value in (".mp3", ".wav", ".ogg", ".flac", ".pcm"):
            self.output_extension.addItem(value, value)
        options_layout.addRow("Split", self.split_mode)
        options_layout.addRow("Filename prefix", self.filename_prefix)
        options_layout.addRow("Start number", self.start_index)
        options_layout.addRow("Output extension", self.output_extension)
        self.split_mode.currentIndexChanged.connect(self.refresh_preview)
        self.filename_prefix.textChanged.connect(self.refresh_preview)
        self.start_index.valueChanged.connect(self.refresh_preview)
        self.output_extension.currentIndexChanged.connect(self.refresh_preview)
        root.addWidget(options)

        summary_row = QHBoxLayout()
        self.summary = QLabel("0 jobs · 0 characters")
        self.summary.setObjectName("textSourceSummary")
        refresh = QPushButton("Refresh preview")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh_preview)
        summary_row.addWidget(self.summary)
        summary_row.addStretch()
        summary_row.addWidget(refresh)
        root.addLayout(summary_row)

        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(["Filename", "Characters", "Text preview"])
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.preview.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.preview, 3)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add to project")
        self.buttons.button(QDialogButtonBox.Ok).setIcon(action_icon("project.add_sources"))
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.refresh_preview()

    def _manual_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        self.manual_text = QTextEdit()
        self.manual_text.setAcceptRichText(False)
        self.manual_text.setPlaceholderText("Type or paste the text that should be converted to speech…")
        self.manual_text.textChanged.connect(self.refresh_preview)
        layout.addWidget(self.manual_text)
        return page

    def _files_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        actions = QHBoxLayout()
        add = QPushButton("Add files")
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
        note = QLabel("Supported: .txt, .text, .md, .markdown, .rtf, .docx, .html, .htm and .odt")
        note.setObjectName("formHint")
        layout.addWidget(note)
        return page

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add text documents",
            str(Path.home()),
            "Text documents (*.txt *.text *.md *.markdown *.rtf *.docx *.html *.htm *.odt)",
        )
        existing = {str(path.resolve()).casefold() for path in self.file_paths}
        for raw_path in paths:
            path = Path(raw_path)
            key = str(path.resolve()).casefold()
            if key not in existing:
                self.file_paths.append(path)
                self.file_list.addItem(str(path))
                existing.add(key)
        if paths and not self.filename_prefix.text().strip():
            self.filename_prefix.setText(Path(paths[0]).stem)
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
            prefix = self.filename_prefix.text().strip() or ("manual" if self.tabs.currentIndex() == 0 else "")
            extension = self.output_extension.currentData() or ".mp3"
            if self.tabs.currentIndex() == 0:
                self.entries = self.service.entries_from_manual(
                    self.manual_text.toPlainText(),
                    split_mode=split_mode,
                    filename_prefix=prefix,
                    start_index=self.start_index.value(),
                    extension=extension,
                )
            else:
                file_mode = "file" if split_mode == "single" else split_mode
                file_prefix = "" if prefix == "manual" else prefix
                self.entries = self.service.entries_from_files(
                    self.file_paths,
                    split_mode=file_mode,
                    filename_prefix=file_prefix,
                    start_index=self.start_index.value(),
                    extension=extension,
                )
            self._render_preview()
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.entries))
        except (OSError, ValueError) as exc:
            self.entries = []
            self._render_preview()
            self.summary.setText(str(exc))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    def _render_preview(self) -> None:
        self.preview.setRowCount(len(self.entries))
        total = 0
        for row, entry in enumerate(self.entries):
            total += entry.character_count
            excerpt = " ".join(entry.text.split())
            if len(excerpt) > 160:
                excerpt = f"{excerpt[:157]}…"
            filename = QTableWidgetItem(entry.filename)
            filename.setToolTip(entry.filename)
            chars = QTableWidgetItem(str(entry.character_count))
            chars.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            preview = QTableWidgetItem(excerpt)
            preview.setToolTip(entry.text)
            self.preview.setItem(row, 0, filename)
            self.preview.setItem(row, 1, chars)
            self.preview.setItem(row, 2, preview)
        self.summary.setText(f"{len(self.entries):,} job(s) · {total:,} characters")

    def _accept(self) -> None:
        self.refresh_preview()
        if not self.entries:
            QMessageBox.warning(self, "Add text source", "Enter text or add at least one readable document.")
            return
        self.accept()

    def source_label(self) -> str:
        if self.tabs.currentIndex() == 0:
            return self.filename_prefix.text().strip() or "manual-text"
        if len(self.file_paths) == 1:
            return self.file_paths[0].stem
        return self.filename_prefix.text().strip() or "text-documents"
