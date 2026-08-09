from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.icons import action_icon
from app.models.text_batch_preparation import TextBatchPreparationSnapshot


class TextBatchPreparationPanel(QFrame):
    """Compact next-action funnel for Text Studio preparation."""

    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("textBatchPreparationPanel")
        self._action = "add-source"
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(7)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Preparation flow")
        title.setObjectName("textBatchPreparationTitle")
        subtitle = QLabel("Input → Structure → Quality → Batch → Queue")
        subtitle.setObjectName("textBatchPreparationSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box, 1)
        self.status_badge = QLabel("Waiting for source")
        self.status_badge.setObjectName("textBatchPreparationStatus")
        self.status_badge.setProperty("tone", "neutral")
        heading.addWidget(self.status_badge)
        root.addLayout(heading)

        stages = QHBoxLayout()
        stages.setSpacing(6)
        self.stage_labels: dict[str, QLabel] = {}
        for code, title_text in (
            ("input", "1 · Input"),
            ("structure", "2 · Structure"),
            ("quality", "3 · Quality"),
            ("batch", "4 · Batch"),
            ("queue", "5 · Queue"),
        ):
            label = QLabel(title_text)
            label.setObjectName("textBatchPreparationStage")
            label.setProperty("status", "pending")
            label.setToolTip("Waiting")
            stages.addWidget(label, 1)
            self.stage_labels[code] = label
        root.addLayout(stages)

        action_row = QHBoxLayout()
        self.detail_label = QLabel("Add or paste source text to begin.")
        self.detail_label.setObjectName("textBatchPreparationDetail")
        self.detail_label.setWordWrap(True)
        action_row.addWidget(self.detail_label, 1)
        self.primary_action = QPushButton("Add or paste source")
        self.primary_action.setObjectName("textBatchPreparationPrimary")
        self.primary_action.setIcon(action_icon("project.add_text_source"))
        self.primary_action.clicked.connect(lambda: self.action_requested.emit(self._action))
        action_row.addWidget(self.primary_action)
        root.addLayout(action_row)

    def set_snapshot(self, snapshot: TextBatchPreparationSnapshot) -> None:
        self._action = snapshot.next_action
        self.primary_action.setText(snapshot.next_label)
        self.detail_label.setText(snapshot.next_detail)
        status = (
            "Ready for queue"
            if snapshot.ready_for_queue and snapshot.duplicate_texts == 0
            else snapshot.next_label
        )
        self.status_badge.setText(status)
        self._set_dynamic_property(self.status_badge, "tone", snapshot.tone)
        for stage in snapshot.stages:
            label = self.stage_labels.get(stage.code)
            if label is None:
                continue
            self._set_dynamic_property(label, "status", stage.status)
            label.setToolTip(stage.detail)
        icon_name = {
            "add-source": "project.add_text_source",
            "safe-prepare": "general.refresh",
            "review-duplicates": "report",
            "review-quality": "report",
            "queue": "project.add_sources",
        }.get(snapshot.next_action, "general.info")
        self.primary_action.setIcon(action_icon(icon_name))

    @staticmethod
    def _set_dynamic_property(widget: QWidget, name: str, value: str) -> None:
        if widget.property(name) == value:
            return
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
