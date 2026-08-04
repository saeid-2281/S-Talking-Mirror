from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.ux_accessibility import UxAccessibilitySnapshot
from app.services.ux_accessibility_certification_service import (
    UxAccessibilityCertificationService,
)


class UxAccessibilityCertificationDialog(QDialog):
    """Final certification workspace for themes, keyboard access and scaling."""

    def __init__(
        self,
        service: UxAccessibilityCertificationService,
        parent: QWidget | None = None,
        *,
        themes_provider: Callable[[], Mapping[str, Mapping[str, str]]] | None = None,
        active_theme_provider: Callable[[], str] | None = None,
        preference_summary_provider: Callable[[], str] | None = None,
        widget_records_provider: Callable[[], tuple[dict[str, object], ...]] | None = None,
        shortcut_provider: Callable[[], tuple[dict[str, object], ...]] | None = None,
        focus_regions_provider: Callable[[], tuple[str, ...]] | None = None,
        apply_recommended_preset: Callable[[], None] | None = None,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.themes_provider = themes_provider or (lambda: {})
        self.active_theme_provider = active_theme_provider or (lambda: "")
        self.preference_summary_provider = preference_summary_provider or (lambda: "")
        self.widget_records_provider = widget_records_provider or (lambda: ())
        self.shortcut_provider = shortcut_provider or (lambda: ())
        self.focus_regions_provider = focus_regions_provider or (lambda: ())
        self.apply_recommended_preset_callback = apply_recommended_preset
        self.open_path = open_path
        self.current_snapshot: UxAccessibilitySnapshot | None = None
        self.last_export: tuple[Path, Path] | None = None

        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("uxAccessibilityCertificationDialog")
        self.setWindowTitle("UX, accessibility and theme certification")
        self.resize(1240, 820)
        self.setMinimumSize(940, 650)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "UX, accessibility and theme certification",
            "Certify Dark, Graphite and Light themes, selection contrast, keyboard focus, target sizes, display scaling and assistive-technology contracts without reading project content.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.summary = DialogStatusCard("Collecting UX evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("uxCertificationTabs")
        self.tabs.setAccessibleName("UX certification evidence")
        self.workspace.add_body_widget(self.tabs, 1)

        self.gate_table = self._table(
            ["Status", "Category", "Control", "Evidence", "Action"],
            "uxCertificationGateTable",
        )
        self.tabs.addTab(self._tab("Release gates", self.gate_table), "Certification gates")

        self.contrast_table = self._table(
            ["Theme", "Role", "Foreground", "Background", "Ratio", "Required", "Status"],
            "uxCertificationContrastTable",
        )
        self.tabs.addTab(self._tab("WCAG-oriented token checks", self.contrast_table), "Theme contrast")

        self.issue_table = self._table(
            ["Severity", "Category", "Widget", "Type", "Issue", "Remediation"],
            "uxCertificationIssueTable",
        )
        self.tabs.addTab(self._tab("Runtime widget and shortcut findings", self.issue_table), "Runtime issues")

        self.display_table = self._table(
            ["Display scale", "Minimum viewport", "Certified text", "Status", "Evidence"],
            "uxCertificationDisplayTable",
        )
        self.tabs.addTab(self._tab("Windows DPI and scaling profiles", self.display_table), "Display profiles")

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("UX certification status")
        self.workspace.add_footer_widget(self.status_label, 1)

        for text, handler, icon_name, primary in (
            ("Refresh certification", self.refresh, "general.refresh", True),
            ("Apply certified preset", self.apply_preset, "settings", False),
            ("Export JSON and CSV", self.export_snapshot, "save", False),
            ("Open evidence folder", self.open_evidence_folder, "project.output_folder", False),
        ):
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.setAccessibleName(text)
            button.clicked.connect(handler)
            if primary:
                button.setObjectName("dialogPrimaryAction")
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.setAccessibleName("Close UX certification")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    @staticmethod
    def _table(headers: list[str], object_name: str) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName(object_name)
        table.setAccessibleName(" ".join(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        return table

    @staticmethod
    def _tab(title: str, table: QTableWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        section = DialogSection(title, "Evidence is generated from public UI metadata and certified design tokens.")
        section.add_widget(table)
        layout.addWidget(section)
        return tab

    def _snapshot(self) -> UxAccessibilitySnapshot:
        return self.service.certification_snapshot(
            themes=self.themes_provider(),
            active_theme=self.active_theme_provider(),
            preference_summary=self.preference_summary_provider(),
            widget_records=self.widget_records_provider(),
            shortcuts=self.shortcut_provider(),
            focus_regions=self.focus_regions_provider(),
        )

    def refresh(self) -> UxAccessibilitySnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        tone = "error" if snapshot.status == "blocked" else "warning" if snapshot.status == "attention" else "success"
        self.summary.update_status(
            snapshot.summary,
            (
                f"Theme {snapshot.active_theme or 'unknown'} · {snapshot.audited_widget_count} interactive metadata record(s) · "
                f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
            ),
            tone=tone,
        )

        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status.replace("_", " ").title(),
                gate.category.replace("-", " ").title(),
                gate.label,
                gate.detail,
                gate.remediation or "—",
            )
            self._set_row(self.gate_table, row, values)
        self.gate_table.resizeColumnsToContents()

        self.contrast_table.setRowCount(len(snapshot.contrast_results))
        for row, result in enumerate(snapshot.contrast_results):
            values = (
                result.theme,
                result.role,
                result.foreground,
                result.background,
                f"{result.ratio:.2f}:1",
                f"{result.required_ratio:.1f}:1",
                result.status.title(),
            )
            self._set_row(self.contrast_table, row, values)
        self.contrast_table.resizeColumnsToContents()

        self.issue_table.setRowCount(len(snapshot.issues))
        for row, issue in enumerate(snapshot.issues):
            values = (
                issue.severity.title(),
                issue.category.replace("-", " ").title(),
                issue.widget_path,
                issue.widget_type,
                issue.detail,
                issue.remediation,
            )
            self._set_row(self.issue_table, row, values)
        self.issue_table.resizeColumnsToContents()

        self.display_table.setRowCount(len(snapshot.display_profiles))
        for row, profile in enumerate(snapshot.display_profiles):
            values = (
                f"{profile.scale_percent}%",
                f"{profile.minimum_width} × {profile.minimum_height}",
                f"{profile.text_scale_percent}%",
                profile.status.title(),
                profile.detail,
            )
            self._set_row(self.display_table, row, values)
        self.display_table.resizeColumnsToContents()
        self.status_label.setText(
            f"{snapshot.status.replace('_', ' ').title()} · {snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
        )
        return snapshot

    @staticmethod
    def _set_row(table: QTableWidget, row: int, values: tuple[object, ...]) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row, column, item)

    def apply_preset(self) -> None:
        if self.apply_recommended_preset_callback is not None:
            self.apply_recommended_preset_callback()
            self.status_label.setText("Certified accessibility preset applied.")
            self.refresh()

    def export_snapshot(self) -> tuple[Path, Path] | None:
        snapshot = self.current_snapshot or self.refresh()
        self.last_export = self.service.export_snapshot(snapshot)
        self.status_label.setText(
            f"Exported {self.last_export[0].name} and {self.last_export[1].name}"
        )
        return self.last_export

    def open_evidence_folder(self) -> None:
        self.service.export_dir.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.export_dir)
