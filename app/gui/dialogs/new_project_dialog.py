from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        layout = QFormLayout(self)
        self.name = QLineEdit("Untitled project")
        self.csv = QLineEdit()
        self.output = QLineEdit(str(Path("output").absolute()))

        csv_browse = QPushButton("Browse")
        csv_browse.clicked.connect(self.pick_csv)
        csv_row = QHBoxLayout()
        csv_row.addWidget(self.csv)
        csv_row.addWidget(csv_browse)

        output_browse = QPushButton("Browse")
        output_browse.clicked.connect(self.pick_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output)
        output_row.addWidget(output_browse)

        layout.addRow("Name", self.name)
        layout.addRow("CSV", csv_row)
        layout.addRow("Output", output_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def pick_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "CSV", "", "CSV (*.csv)")
        if path:
            self.csv.setText(path)

    def pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output")
        if path:
            self.output.setText(path)

    def values(self) -> tuple[str, Path | None, Path | None]:
        csv_path = Path(self.csv.text()) if self.csv.text().strip() else None
        output_path = Path(self.output.text()) if self.output.text().strip() else None
        return self.name.text().strip() or "Untitled project", csv_path, output_path
