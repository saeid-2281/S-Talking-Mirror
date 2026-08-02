from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.services.text_studio_quality import TextStudioQualitySummary


class TextStudioQualityPanel(QFrame):
    """Preparation checks and batch tools for queue-ready text jobs."""

    issues_only_changed = Signal(bool)
    normalize_selected_requested = Signal()
    normalize_all_requested = Signal()
    remove_duplicates_requested = Signal()
    renumber_requested = Signal()
    replace_selected_requested = Signal(str, str, bool)
    replace_all_requested = Signal(str, str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("textStudioQualityPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Preparation check")
        title.setObjectName("textStudioQualityTitle")
        subtitle = QLabel("Review naming, duplicates, chunk length and whitespace before adding jobs to the queue.")
        subtitle.setObjectName("textStudioQualitySubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box, 1)
        self.status_badge = QLabel("No enabled jobs")
        self.status_badge.setObjectName("textStudioQualityStatus")
        self.status_badge.setProperty("tone", "neutral")
        heading.addWidget(self.status_badge)
        root.addLayout(heading)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.metric_labels: dict[str, QLabel] = {}
        for key, caption in (
            ("enabled", "Enabled"),
            ("characters", "Characters"),
            ("blocking", "Blocking"),
            ("warnings", "Warnings"),
        ):
            card = QFrame()
            card.setObjectName("textStudioQualityMetric")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 4, 8, 4)
            card_layout.setSpacing(0)
            caption_label = QLabel(caption)
            caption_label.setObjectName("textStudioQualityMetricCaption")
            value = QLabel("0")
            value.setObjectName("textStudioQualityMetricValue")
            card_layout.addWidget(caption_label)
            card_layout.addWidget(value)
            metrics.addWidget(card, 1)
            self.metric_labels[key] = value
        root.addLayout(metrics)

        tools = QGridLayout()
        tools.setHorizontalSpacing(8)
        tools.setVerticalSpacing(6)
        self.issues_only = QCheckBox("Issues only")
        self.issues_only.setToolTip("Show only jobs that need review")
        self.issues_only.toggled.connect(self.issues_only_changed)
        normalize_selected = QPushButton("Normalize selected")
        normalize_selected.setIcon(action_icon("general.refresh"))
        normalize_selected.clicked.connect(self.normalize_selected_requested)
        normalize_all = QPushButton("Normalize all")
        normalize_all.clicked.connect(self.normalize_all_requested)
        remove_duplicates = QPushButton("Remove duplicate text")
        remove_duplicates.setIcon(action_icon("general.remove"))
        remove_duplicates.clicked.connect(self.remove_duplicates_requested)
        renumber = QPushButton("Renumber filenames")
        renumber.setIcon(action_icon("general.edit"))
        renumber.clicked.connect(self.renumber_requested)
        tools.addWidget(self.issues_only, 0, 0)
        tools.addWidget(normalize_selected, 0, 1)
        tools.addWidget(normalize_all, 0, 2)
        tools.addWidget(remove_duplicates, 0, 3)
        tools.addWidget(renumber, 0, 4)

        self.find_edit = QLineEdit()
        self.find_edit.setObjectName("textStudioFindText")
        self.find_edit.setPlaceholderText("Find text…")
        self.find_edit.setClearButtonEnabled(True)
        self.replace_edit = QLineEdit()
        self.replace_edit.setObjectName("textStudioReplaceText")
        self.replace_edit.setPlaceholderText("Replace with…")
        self.case_sensitive = QCheckBox("Case sensitive")
        replace_selected = QPushButton("Replace selected")
        replace_selected.clicked.connect(self._emit_replace_selected)
        replace_all = QPushButton("Replace all")
        replace_all.clicked.connect(self._emit_replace_all)
        tools.addWidget(self.find_edit, 1, 0, 1, 2)
        tools.addWidget(self.replace_edit, 1, 2)
        tools.addWidget(self.case_sensitive, 1, 3)
        tools.addWidget(replace_selected, 1, 4)
        tools.addWidget(replace_all, 1, 5)
        tools.setColumnStretch(0, 1)
        tools.setColumnStretch(1, 1)
        tools.setColumnStretch(2, 1)
        root.addLayout(tools)

        self.detail_label = QLabel("Add or paste text to begin preparation checks.")
        self.detail_label.setObjectName("textStudioQualityDetail")
        self.detail_label.setWordWrap(True)
        root.addWidget(self.detail_label)

    def _emit_replace_selected(self) -> None:
        self.replace_selected_requested.emit(
            self.find_edit.text(), self.replace_edit.text(), self.case_sensitive.isChecked()
        )

    def _emit_replace_all(self) -> None:
        self.replace_all_requested.emit(
            self.find_edit.text(), self.replace_edit.text(), self.case_sensitive.isChecked()
        )

    def set_summary(self, summary: TextStudioQualitySummary) -> None:
        self.metric_labels["enabled"].setText(f"{summary.enabled_jobs:,}")
        self.metric_labels["characters"].setText(f"{summary.characters:,}")
        self.metric_labels["blocking"].setText(f"{summary.blocking_issues:,}")
        self.metric_labels["warnings"].setText(f"{summary.warnings:,}")
        self.status_badge.setText(summary.status_text)
        self.status_badge.setProperty("tone", summary.tone)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        parts = []
        if summary.duplicate_filenames:
            parts.append(f"{summary.duplicate_filenames:,} duplicate filename row(s)")
        if summary.invalid_filenames:
            parts.append(f"{summary.invalid_filenames:,} invalid filename(s)")
        if summary.duplicate_texts:
            parts.append(f"{summary.duplicate_texts:,} duplicate text row(s)")
        if summary.oversized_chunks:
            parts.append(f"{summary.oversized_chunks:,} oversized chunk(s)")
        if summary.whitespace_issues:
            parts.append(f"{summary.whitespace_issues:,} whitespace warning(s)")
        self.detail_label.setText(" · ".join(parts) if parts else "All enabled jobs passed preparation checks.")
