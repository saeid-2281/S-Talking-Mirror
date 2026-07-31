from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentActionItem,
    GenerationIncidentReview,
)
from app.services.generation_incident_service import GenerationIncidentService


class GenerationIncidentReviewDialog(QDialog):
    """Edit a post-incident review and track corrective actions."""

    def __init__(
        self,
        service: GenerationIncidentService,
        incident: GenerationIncident,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.incident = incident
        self.review = self.service.get_or_create_review(incident.incident_id)
        self.actions: list[GenerationIncidentActionItem] = []
        self.setWindowTitle("Post-Incident Review")
        self.resize(1080, 780)
        self._build_ui()
        self._load_review(self.review)
        self.refresh_actions()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel(f"Post-Incident Review · {self.incident.incident_id}")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        root.addWidget(title)
        self.review_state = QLabel()
        root.addWidget(self.review_state)

        splitter = QSplitter(Qt.Vertical)
        review_widget = QWidget()
        form = QFormLayout(review_widget)
        self.reviewer = QLineEdit()
        self.root_cause_category = QComboBox()
        for value in sorted(self.service.VALID_ROOT_CAUSE_CATEGORIES):
            self.root_cause_category.addItem(value.replace("_", " ").title(), value)
        self.impact_summary = QPlainTextEdit()
        self.root_cause = QPlainTextEdit()
        self.contributing_factors = QPlainTextEdit()
        self.contributing_factors.setPlaceholderText("One contributing factor per line")
        self.detection_gap = QPlainTextEdit()
        self.resolution_summary = QPlainTextEdit()
        self.lessons_learned = QPlainTextEdit()
        for editor in (
            self.impact_summary,
            self.root_cause,
            self.contributing_factors,
            self.detection_gap,
            self.resolution_summary,
            self.lessons_learned,
        ):
            editor.setMaximumHeight(105)
        form.addRow("Reviewer", self.reviewer)
        form.addRow("Root-cause category", self.root_cause_category)
        form.addRow("Impact summary", self.impact_summary)
        form.addRow("Root cause", self.root_cause)
        form.addRow("Contributing factors", self.contributing_factors)
        form.addRow("Detection gap", self.detection_gap)
        form.addRow("Resolution summary", self.resolution_summary)
        form.addRow("Lessons learned", self.lessons_learned)
        splitter.addWidget(review_widget)

        actions_widget = QWidget()
        actions_layout = QVBoxLayout(actions_widget)
        actions_layout.addWidget(QLabel("Corrective actions"))
        self.actions_table = QTableWidget(0, 6)
        self.actions_table.setHorizontalHeaderLabels(
            ["Status", "Priority", "Due", "Owner", "Action", "Note"]
        )
        self.actions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.actions_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.actions_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.actions_table.verticalHeader().setVisible(False)
        header = self.actions_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        actions_layout.addWidget(self.actions_table)
        action_buttons = QHBoxLayout()
        for label, handler in (
            ("Add action", self.add_action),
            ("Edit", self.edit_action),
            ("Start", lambda: self.set_action_status("in_progress")),
            ("Complete", lambda: self.set_action_status("completed")),
            ("Cancel", lambda: self.set_action_status("cancelled")),
            ("Reopen", lambda: self.set_action_status("open")),
            ("Delete", self.delete_action),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            action_buttons.addWidget(button)
        action_buttons.addStretch(1)
        actions_layout.addLayout(action_buttons)
        splitter.addWidget(actions_widget)
        splitter.setSizes([460, 260])
        root.addWidget(splitter, 1)

        self.status_label = QLabel()
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        save = QPushButton("Save draft")
        save.clicked.connect(self.save_draft)
        complete = QPushButton("Complete review")
        complete.clicked.connect(self.complete_review)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(save)
        footer.addWidget(complete)
        footer.addWidget(refresh)
        footer.addStretch(1)
        footer.addWidget(close)
        root.addLayout(footer)

    def _load_review(self, review: GenerationIncidentReview) -> None:
        self.review = review
        self.reviewer.setText(review.reviewer or "")
        index = self.root_cause_category.findData(review.root_cause_category)
        self.root_cause_category.setCurrentIndex(max(0, index))
        self.impact_summary.setPlainText(review.impact_summary)
        self.root_cause.setPlainText(review.root_cause)
        self.contributing_factors.setPlainText("\n".join(review.contributing_factors))
        self.detection_gap.setPlainText(review.detection_gap)
        self.resolution_summary.setPlainText(review.resolution_summary)
        self.lessons_learned.setPlainText(review.lessons_learned)
        completed = f" · completed {review.completed_at}" if review.completed_at else ""
        self.review_state.setText(
            f"Status: {review.status.title()} · incident: {self.incident.status.title()}{completed}"
        )

    def _collected_review(self) -> GenerationIncidentReview:
        factors = tuple(
            line.strip()
            for line in self.contributing_factors.toPlainText().splitlines()
            if line.strip()
        )
        return replace(
            self.review,
            impact_summary=self.impact_summary.toPlainText(),
            root_cause_category=str(self.root_cause_category.currentData() or "unknown"),
            root_cause=self.root_cause.toPlainText(),
            contributing_factors=factors,
            detection_gap=self.detection_gap.toPlainText(),
            resolution_summary=self.resolution_summary.toPlainText(),
            lessons_learned=self.lessons_learned.toPlainText(),
            reviewer=self.reviewer.text(),
        )

    def save_draft(self) -> None:
        try:
            self.review = self.service.save_review(self._collected_review())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_review(self.review)
        self.status_label.setText("Review draft saved.")

    def complete_review(self) -> None:
        try:
            self.review = self.service.save_review(
                self._collected_review(),
                complete=True,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_review(self.review)
        self.status_label.setText("Post-incident review completed.")

    def refresh(self) -> None:
        review = self.service.get_review(self.incident.incident_id)
        if review is not None:
            self._load_review(review)
        self.refresh_actions()
        self.status_label.setText("Review refreshed.")

    def refresh_actions(self) -> None:
        self.actions = self.service.list_action_items(self.incident.incident_id)
        self.actions_table.setRowCount(len(self.actions))
        for row, action in enumerate(self.actions):
            due = action.due_at or "—"
            if self._is_overdue(action):
                due = f"OVERDUE · {due}"
            values = (
                action.status.replace("_", " ").title(),
                action.priority.upper(),
                due.replace("T", " ")[:26],
                action.owner or "Unassigned",
                action.title,
                action.note,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, action.action_id)
                self.actions_table.setItem(row, column, item)
        self.actions_table.clearSelection()

    def selected_action(self) -> GenerationIncidentActionItem | None:
        rows = sorted({index.row() for index in self.actions_table.selectedIndexes()})
        if not rows:
            current = self.actions_table.currentRow()
            if current >= 0:
                rows = [current]
        if not rows:
            return None
        row = rows[0]
        item = self.actions_table.item(row, 0)
        action_id = str(item.data(Qt.UserRole) or "") if item is not None else ""
        return next((item for item in self.actions if item.action_id == action_id), None)

    def add_action(self) -> None:
        title, accepted = QInputDialog.getText(self, "Add corrective action", "Action:")
        if not accepted or not title.strip():
            return
        owner, accepted = QInputDialog.getText(self, "Action owner", "Owner (optional):")
        if not accepted:
            return
        due_at, accepted = QInputDialog.getText(
            self,
            "Action due date",
            "Due date/time in ISO-8601 format (optional):",
        )
        if not accepted:
            return
        priority, accepted = QInputDialog.getItem(
            self,
            "Action priority",
            "Priority:",
            ["p1", "p2", "p3", "p4"],
            1,
            False,
        )
        if not accepted:
            return
        try:
            action = self.service.add_action_item(
                self.incident.incident_id,
                title,
                owner=owner,
                due_at=due_at,
                priority=priority,
                actor=self.reviewer.text(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh_actions()
        self.status_label.setText(f"Corrective action added: {action.title}")

    def edit_action(self) -> None:
        action = self.selected_action()
        if action is None:
            self.status_label.setText("Select one corrective action.")
            return
        title, accepted = QInputDialog.getText(
            self,
            "Edit corrective action",
            "Action:",
            text=action.title,
        )
        if not accepted or not title.strip():
            return
        owner, accepted = QInputDialog.getText(
            self,
            "Action owner",
            "Owner (blank clears assignment):",
            text=action.owner or "",
        )
        if not accepted:
            return
        due_at, accepted = QInputDialog.getText(
            self,
            "Action due date",
            "Due date/time in ISO-8601 format (blank clears it):",
            text=action.due_at or "",
        )
        if not accepted:
            return
        priorities = ["p1", "p2", "p3", "p4"]
        priority, accepted = QInputDialog.getItem(
            self,
            "Action priority",
            "Priority:",
            priorities,
            max(0, priorities.index(action.priority) if action.priority in priorities else 1),
            False,
        )
        if not accepted:
            return
        note, accepted = QInputDialog.getMultiLineText(
            self,
            "Action note",
            "Note:",
            action.note,
        )
        if not accepted:
            return
        try:
            updated = self.service.update_action_item(
                action.action_id,
                title=title,
                owner=owner,
                due_at=due_at,
                priority=priority,
                note=note,
                actor=self.reviewer.text(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh_actions()
        self.status_label.setText(f"Corrective action updated: {updated.title}")

    def set_action_status(self, status: str) -> None:
        action = self.selected_action()
        if action is None:
            self.status_label.setText("Select one corrective action.")
            return
        try:
            updated = self.service.update_action_item(
                action.action_id,
                status=status,
                actor=self.reviewer.text(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh_actions()
        self.status_label.setText(
            f"Action '{updated.title}' changed to {updated.status.replace('_', ' ')}."
        )

    def delete_action(self) -> None:
        action = self.selected_action()
        if action is None:
            self.status_label.setText("Select one corrective action.")
            return
        if QMessageBox.question(
            self,
            "Delete corrective action",
            f"Delete '{action.title}'?",
        ) != QMessageBox.Yes:
            return
        count = self.service.delete_action_item(
            action.action_id,
            actor=self.reviewer.text(),
        )
        self.refresh_actions()
        self.status_label.setText(f"Deleted {count} corrective action(s).")

    @staticmethod
    def _is_overdue(action: GenerationIncidentActionItem) -> bool:
        if action.status not in {"open", "in_progress"} or not action.due_at:
            return False
        from datetime import datetime, timezone

        try:
            due = datetime.fromisoformat(action.due_at)
        except ValueError:
            return False
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > due.astimezone(timezone.utc)
