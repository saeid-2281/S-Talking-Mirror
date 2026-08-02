from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace


class NewProjectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        csv_dir: Path | None = None,
        output_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.csv_dir = csv_dir or Path.cwd()
        self.output_dir = output_dir or Path("output").absolute()
        self.setObjectName("newProjectDialog")
        self.setWindowTitle("New Project")
        self.resize(720, 500)
        self.setMinimumSize(520, 390)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.workspace = DialogWorkspace(
            "Create a new project",
            "Name the workspace, optionally attach an initial CSV source, and choose where generated audio will be stored.",
            icon_name="project.new",
            parent=self,
        )
        root.addWidget(self.workspace)

        section = DialogSection(
            "Project details",
            "The source file can be added later. The output folder is required so generation has a predictable destination.",
        )
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.name = QLineEdit("Untitled project")
        self.name.setObjectName("newProjectName")
        self.name.setClearButtonEnabled(True)
        self.name.setAccessibleName("Project name")
        form.addRow("Project name", self.name)

        self.csv = QLineEdit()
        self.csv.setObjectName("newProjectCsv")
        self.csv.setPlaceholderText("Optional initial CSV source")
        self.csv.setClearButtonEnabled(True)
        self.csv.setAccessibleName("Initial CSV source")
        csv_browse = QPushButton("Browse CSV")
        csv_browse.setObjectName("newProjectBrowseCsv")
        csv_browse.setIcon(action_icon("project.add_sources"))
        csv_browse.clicked.connect(self.pick_csv)
        csv_row = QHBoxLayout()
        csv_row.setContentsMargins(0, 0, 0, 0)
        csv_row.setSpacing(8)
        csv_row.addWidget(self.csv, 1)
        csv_row.addWidget(csv_browse)
        form.addRow("Initial source", csv_row)

        self.output = QLineEdit(str(self.output_dir))
        self.output.setObjectName("newProjectOutput")
        self.output.setClearButtonEnabled(True)
        self.output.setAccessibleName("Project output folder")
        output_browse = QPushButton("Browse folder")
        output_browse.setObjectName("newProjectBrowseOutput")
        output_browse.setIcon(action_icon("project.output_folder"))
        output_browse.clicked.connect(self.pick_output)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        output_row.addWidget(self.output, 1)
        output_row.addWidget(output_browse)
        form.addRow("Output folder", output_row)

        section.add_layout(form)
        self.workspace.add_body_widget(section)

        self.location_summary = DialogStatusCard(
            "Ready to create",
            "The project file can be saved after creation. Sources and provider settings remain editable.",
            tone="info",
        )
        self.workspace.add_body_widget(self.location_summary)
        self.workspace.add_body_stretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("newProjectCancel")
        cancel.clicked.connect(self.reject)
        self.create_button = QPushButton("Create project")
        self.create_button.setObjectName("dialogPrimaryAction")
        self.create_button.setIcon(action_icon("project.new"))
        self.create_button.clicked.connect(self.accept)
        self.workspace.add_footer_stretch()
        self.workspace.add_footer_widget(cancel)
        self.workspace.add_footer_widget(self.create_button)

        self.name.textChanged.connect(self._update_state)
        self.output.textChanged.connect(self._update_state)
        self.csv.textChanged.connect(self._update_state)
        self._update_state()

    def pick_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "CSV", str(self.csv_dir), "CSV (*.csv)")
        if path:
            self.csv.setText(path)

    def pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output", str(self.output_dir))
        if path:
            self.output.setText(path)

    def _update_state(self) -> None:
        name = self.name.text().strip()
        output = self.output.text().strip()
        self.create_button.setEnabled(bool(name and output))
        if not name:
            self.location_summary.update_status(
                "Project name required",
                "Enter a short, recognizable project name before continuing.",
                tone="warning",
            )
        elif not output:
            self.location_summary.update_status(
                "Output folder required",
                "Choose where generated audio files should be stored.",
                tone="warning",
            )
        else:
            source = Path(self.csv.text()).name if self.csv.text().strip() else "No initial source"
            self.location_summary.update_status(
                "Ready to create",
                f"{source} · Output: {output}",
                tone="success",
            )

    def values(self) -> tuple[str, Path | None, Path | None]:
        csv_path = Path(self.csv.text()) if self.csv.text().strip() else None
        output_path = Path(self.output.text()) if self.output.text().strip() else None
        return self.name.text().strip() or "Untitled project", csv_path, output_path
