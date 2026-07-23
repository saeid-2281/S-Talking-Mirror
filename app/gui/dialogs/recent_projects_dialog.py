from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.persistence import ProjectRecord


class RecentProjectsDialog(QDialog):
    def __init__(self, projects: list[ProjectRecord], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.projects = projects
        self.selected_project: ProjectRecord | None = None
        self.removed_project_id: int | None = None
        self.setWindowTitle("Recent Projects")
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Path", "Provider", "Last opened"])
        self.table.itemSelectionChanged.connect(self.select_current)
        layout.addWidget(self.table)

        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(remove)
        row.addStretch()
        row.addWidget(buttons)
        layout.addLayout(row)
        self.populate()

    def populate(self) -> None:
        self.table.setRowCount(len(self.projects))
        for row, project in enumerate(self.projects):
            path = project.project_file or ""
            missing = path and not Path(path).exists()
            values = [
                project.name,
                f"{path} (missing)" if missing else path,
                project.provider,
                project.last_opened_at or project.updated_at,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def select_current(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        self.selected_project = self.projects[rows[0].row()] if rows else None

    def remove_selected(self) -> None:
        self.select_current()
        if self.selected_project is not None:
            self.removed_project_id = self.selected_project.id
            self.reject()
