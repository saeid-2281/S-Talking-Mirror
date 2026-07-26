from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import ApplicationContext
from app.models.dashboard_state import DashboardState
from app.models.health_state import HealthState


class HealthCenterDialog(QDialog):
    """Non-modal health overview with score breakdown and smart actions."""

    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        super().__init__(parent)
        self.context = context
        self.dashboard = DashboardState()
        self.state: HealthState | None = None
        self.setWindowTitle("S Talking Health Center")
        self.setModal(False)
        self.resize(840, 680)
        root = QVBoxLayout(self)

        self.headline = QLabel()
        self.headline.setObjectName("healthHeadline")
        self.headline.setAlignment(Qt.AlignCenter)
        self.score = QLabel()
        self.score.setAlignment(Qt.AlignCenter)
        self.score.setObjectName("healthScore")

        self.breakdown = QTreeWidget()
        self.breakdown.setHeaderLabels(["Category", "Score", "Status", "Details"])
        self.breakdown.setRootIsDecorated(False)
        self.breakdown.setAlternatingRowColors(True)
        self.breakdown.setMaximumHeight(210)

        self.recommendations = QPlainTextEdit()
        self.recommendations.setReadOnly(True)
        self.recommendations.setMaximumHeight(110)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)

        root.addWidget(self.headline)
        root.addWidget(self.score)
        root.addWidget(self.breakdown)
        root.addWidget(QLabel("Recommended next actions"))
        root.addWidget(self.recommendations)
        root.addWidget(self.details, 1)

        actions = QHBoxLayout()
        for label, callback in [
            ("Refresh", self.refresh),
            ("Copy summary", self.copy_compact),
            ("Copy for ChatGPT", self.copy_markdown),
            ("Run checks", self.run_checks),
            ("Export diagnostics", self.export_diagnostics),
            ("Open latest report", self.open_latest_report),
            ("Close", self.close),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        root.addLayout(actions)

    def set_dashboard(self, dashboard: DashboardState) -> None:
        self.dashboard = dashboard
        self.refresh()

    def refresh(self) -> None:
        self.state = self.context.health_service.snapshot(
            project=self.context.project_controller.current_project,
            dashboard=self.dashboard,
        )
        color = {"healthy": "#22C55E", "warning": "#F59E0B", "error": "#EF4444"}[self.state.level]
        self.headline.setText(f"{self.state.icon}  {self.state.label}")
        self.headline.setStyleSheet(f"font-size:22px;font-weight:700;color:{color};")
        self.score.setText(f"Health score: {self.state.score}/100")
        self.score.setStyleSheet("font-size:18px;font-weight:600;")

        self.breakdown.clear()
        status_label = {"passed": "Passed", "warning": "Warning", "error": "Error", "neutral": "Info"}
        for item in self.state.breakdown:
            row = QTreeWidgetItem(
                [item.name, f"{item.points}/{item.maximum}", status_label.get(item.status, item.status), item.detail]
            )
            self.breakdown.addTopLevelItem(row)
        for index in range(4):
            self.breakdown.resizeColumnToContents(index)

        self.recommendations.setPlainText("\n".join(f"• {item}" for item in self.state.recommendations))
        self.details.setPlainText(self.context.health_service.markdown_summary(self.state))

    def copy_compact(self) -> None:
        if self.state is None:
            self.refresh()
        self.context.desktop_service.copy_to_clipboard(
            self.context.health_service.compact_summary(self.state)
        )

    def copy_markdown(self) -> None:
        if self.state is None:
            self.refresh()
        self.context.desktop_service.copy_to_clipboard(
            self.context.health_service.markdown_summary(self.state)
        )

    def run_checks(self) -> None:
        parent = self.parent()
        tools = getattr(parent, "developer_tools", None)
        if tools:
            tools.show_checks()

    def export_diagnostics(self) -> None:
        bundle = self.context.diagnostics_service.export_bundle(
            project=self.context.project_controller.current_project,
            dashboard=self.dashboard,
            queue_state={
                "active": self.context.generation_controller.is_active,
                "paused": self.context.generation_controller.is_paused,
            },
        )
        self.context.health_service.invalidate()
        self.context.desktop_service.copy_to_clipboard(str(bundle))
        self.context.desktop_service.open_path(bundle.parent)
        self.refresh()

    def open_latest_report(self) -> None:
        report = self.context.report_service.latest_report_dir()
        if report:
            self.context.desktop_service.open_file(report / "report.html")
