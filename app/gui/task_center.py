from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import ApplicationContext
from app.services.task_prompt_service import TASK_STATUSES, TaskPrompt


class TaskCenterDialog(QDialog):
    """Lists repository task documents and exposes their Codex prompts."""

    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        super().__init__(parent)
        self.context = context
        self.current_task: TaskPrompt | None = None
        self.setWindowTitle("S Talking Task Center")
        self.setModal(False)
        self.resize(980, 620)
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Current development tasks"))
        header.addStretch()
        self.status = QComboBox()
        self.status.addItems(TASK_STATUSES)
        self.status.currentTextChanged.connect(self.change_status)
        header.addWidget(QLabel("Status"))
        header.addWidget(self.status)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        self.tasks = QListWidget()
        self.tasks.currentItemChanged.connect(self.select_task)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.tasks)
        splitter.addWidget(self.details)
        splitter.setSizes([280, 700])
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        for label, callback in [
            ("Refresh", self.refresh),
            ("Copy Codex prompt", self.copy_prompt),
            ("Copy task summary", self.copy_summary),
            ("Open task file", self.open_task),
            ("Close", self.close),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        selected = self.current_task.path if self.current_task else None
        self.tasks.clear()
        for path in self.context.task_prompt_service.list_tasks():
            task = self.context.task_prompt_service.load(path)
            item = QListWidgetItem(f"[{task.status}] {task.title}")
            item.setData(Qt.UserRole, path)
            self.tasks.addItem(item)
            if selected and path == selected:
                self.tasks.setCurrentItem(item)
        if self.tasks.count() and self.tasks.currentRow() < 0:
            self.tasks.setCurrentRow(0)

    def select_task(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self.current_task = None
            self.details.clear()
            return
        path = Path(current.data(Qt.UserRole))
        self.current_task = self.context.task_prompt_service.load(path)
        self.status.blockSignals(True)
        self.status.setCurrentText(self.current_task.status)
        self.status.blockSignals(False)
        self.details.setPlainText(self._task_text(self.current_task))

    def change_status(self, status: str) -> None:
        if not self.current_task:
            return
        self.context.task_prompt_service.update_status(self.current_task.path, status)
        self.current_task = self.context.task_prompt_service.load(self.current_task.path)
        self.refresh()

    def copy_prompt(self) -> None:
        if self.current_task:
            self.context.desktop_service.copy_to_clipboard(self.current_task.codex_prompt)

    def copy_summary(self) -> None:
        if self.current_task:
            self.context.desktop_service.copy_to_clipboard(self._task_text(self.current_task))

    def open_task(self) -> None:
        if self.current_task:
            self.context.desktop_service.open_file(self.current_task.path)

    @staticmethod
    def _task_text(task: TaskPrompt) -> str:
        return (
            f"# {task.title}\n\n"
            f"Status: {task.status}\n"
            f"Branch: {task.branch or 'Not specified'}\n\n"
            f"## Goal\n{task.goal or 'Not specified'}\n\n"
            f"## Acceptance Criteria\n{task.acceptance_criteria or 'Not specified'}\n\n"
            f"## Codex Prompt\n{task.codex_prompt or 'Not specified'}\n"
        )
