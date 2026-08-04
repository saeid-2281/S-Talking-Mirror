from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.update_delivery_controller import UpdateDeliveryController
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.update_delivery import UpdateCheckSnapshot, UpdatePreferences
from app.services.update_delivery_service import UpdateDeliveryService


class UpdateDeliveryDialog(QDialog):
    """Manage update preferences, checks and verified downloads without installing."""

    def __init__(
        self,
        service: UpdateDeliveryService,
        parent: QWidget | None = None,
        *,
        open_path=None,
        copy_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.copy_path = copy_path
        self.current_snapshot: UpdateCheckSnapshot | None = None
        self.controller = UpdateDeliveryController(service, parent=self)
        self.controller.started.connect(self._operation_started)
        self.controller.completed.connect(self._operation_completed)
        self.controller.failed.connect(self._operation_failed)
        self.controller.busy_changed.connect(self._set_busy)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("updateDeliveryDialog")
        self.setWindowTitle("Update channels and release delivery")
        self.resize(1180, 800)
        self.setMinimumSize(860, 620)
        self._build()
        self._load_preferences()
        self._render_idle()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Update channels and release delivery",
            "Check verified preview, beta or stable feeds, review release notes and download an artifact without automatic installation or restart.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Update checks are idle", "No feed has been checked in this session.", tone="info")
        self.workspace.add_body_widget(self.summary)

        preferences = DialogSection(
            "Update preferences",
            "Update checks remain opt-in. A configured feed must use HTTPS or a verified local path.",
        )
        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox("Enable update checks")
        self.enabled.setObjectName("updateDeliveryEnabled")
        self.check_on_startup = QCheckBox("Check in the background when the application starts")
        self.check_on_startup.setObjectName("updateDeliveryStartup")
        self.channel = QComboBox()
        self.channel.setObjectName("updateDeliveryChannel")
        self.channel.addItems(["preview", "beta", "stable"])
        self.feed_url = QLineEdit()
        self.feed_url.setObjectName("updateDeliveryFeedUrl")
        self.feed_url.setPlaceholderText("https://updates.example.com/preview/latest.json or a local latest.json")
        self.interval = QSpinBox()
        self.interval.setObjectName("updateDeliveryInterval")
        self.interval.setRange(1, 24 * 30)
        self.interval.setSuffix(" hours")
        self.prefer_installer = QCheckBox("Prefer a signed Windows installer when one is available")
        self.prefer_installer.setObjectName("updateDeliveryPreferInstaller")
        form.addRow("Checks", self.enabled)
        form.addRow("Startup", self.check_on_startup)
        form.addRow("Channel", self.channel)
        form.addRow("Feed", self.feed_url)
        form.addRow("Interval", self.interval)
        form.addRow("Artifact", self.prefer_installer)
        preferences.add_widget(form_host)
        self.workspace.add_body_widget(preferences)

        gates = DialogSection(
            "Verification gates",
            "Feed digest, channel identity, version policy, rollout assignment and artifact metadata are checked before download.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("updateDeliveryGateTable")
        self.gate_table.setHorizontalHeaderLabels(["Status", "Gate", "Severity", "Evidence", "Action"])
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        artifacts = DialogSection(
            "Download candidates",
            "Only canonical relative filenames with a declared size and SHA-256 digest are accepted.",
        )
        self.artifact_table = QTableWidget(0, 6)
        self.artifact_table.setObjectName("updateDeliveryArtifactTable")
        self.artifact_table.setHorizontalHeaderLabels(["Selected", "Role", "Filename", "Size", "SHA-256", "Signature"])
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.artifact_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        artifacts.add_widget(self.artifact_table)
        self.workspace.add_body_widget(artifacts)

        notes = DialogSection(
            "Release notes",
            "Notes are displayed only after they are embedded in the verified feed or downloaded with a matching digest.",
        )
        self.release_notes = QPlainTextEdit()
        self.release_notes.setObjectName("updateDeliveryReleaseNotes")
        self.release_notes.setReadOnly(True)
        self.release_notes.setPlaceholderText("No verified release notes are available.")
        notes.add_widget(self.release_notes)
        self.workspace.add_body_widget(notes)

        secondary_actions = QWidget()
        secondary_layout = QHBoxLayout(secondary_actions)
        secondary_layout.setContentsMargins(0, 0, 0, 0)
        secondary_layout.setSpacing(8)
        self.open_button = QPushButton("Open download folder")
        self.open_button.clicked.connect(self.open_download_folder)
        self.plan_button = QPushButton("Copy install plan")
        self.plan_button.clicked.connect(self.copy_install_plan)
        self.export_button = QPushButton("Export snapshot")
        self.export_button.clicked.connect(self.export_snapshot)
        secondary_layout.addWidget(self.open_button)
        secondary_layout.addWidget(self.plan_button)
        secondary_layout.addWidget(self.export_button)
        secondary_layout.addStretch(1)
        self.workspace.add_body_widget(secondary_actions)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)

        self.save_button = QPushButton("Save preferences")
        self.save_button.setIcon(action_icon("save"))
        self.save_button.clicked.connect(self.save_preferences)
        self.check_button = QPushButton("Check now")
        self.check_button.setObjectName("dialogPrimaryAction")
        self.check_button.setIcon(action_icon("general.refresh"))
        self.check_button.clicked.connect(self.check_now)
        self.download_button = QPushButton("Download verified update")
        self.download_button.setIcon(action_icon("save"))
        self.download_button.clicked.connect(self.download_update)
        self.download_button.setEnabled(False)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        for widget in (
            self.save_button,
            self.check_button,
            self.download_button,
            close_button,
        ):
            self.workspace.add_footer_widget(widget)

    def _load_preferences(self) -> None:
        preferences = self.service.load_preferences()
        self.enabled.setChecked(preferences.enabled)
        self.check_on_startup.setChecked(preferences.check_on_startup)
        self.channel.setCurrentText(preferences.channel)
        self.feed_url.setText(preferences.feed_url)
        self.interval.setValue(preferences.check_interval_hours)
        self.prefer_installer.setChecked(preferences.prefer_installer)

    def _preferences(self) -> UpdatePreferences:
        return UpdatePreferences(
            enabled=self.enabled.isChecked(),
            check_on_startup=self.check_on_startup.isChecked(),
            channel=self.channel.currentText(),
            feed_url=self.feed_url.text().strip(),
            check_interval_hours=self.interval.value(),
            prefer_installer=self.prefer_installer.isChecked(),
        )

    def save_preferences(self) -> UpdatePreferences | None:
        try:
            preferences = self.service.save_preferences(self._preferences())
        except Exception as exc:
            self.status_label.setText(f"Preferences were not saved: {exc}")
            return None
        self.status_label.setText("Update preferences saved.")
        return preferences

    def check_now(self) -> bool:
        if self.save_preferences() is None:
            return False
        started = self.controller.check(self.feed_url.text().strip(), force=True)
        if not started:
            self.status_label.setText("An update operation is already running.")
        return started

    def download_update(self) -> bool:
        if self.current_snapshot is None or not self.current_snapshot.update_available:
            self.status_label.setText("No eligible verified update is available.")
            return False
        started = self.controller.download(self.current_snapshot)
        if not started:
            self.status_label.setText("An update operation is already running.")
        return started

    def _operation_started(self, operation: str) -> None:
        label = "Checking update metadata" if operation == "check" else "Downloading and verifying update"
        self.status_label.setText(f"{label}…")

    def _operation_completed(self, operation: str, result: object) -> None:
        if not isinstance(result, UpdateCheckSnapshot):
            self.status_label.setText("Update operation returned an invalid result.")
            return
        self._render(result)
        if operation == "download" and result.downloaded_path:
            self.status_label.setText(f"Downloaded and verified: {result.downloaded_path.name}")

    def _operation_failed(self, operation: str, message: str) -> None:
        self.status_label.setText(f"{operation.title()} failed: {message}")

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.save_button, self.check_button, self.download_button):
            widget.setEnabled(not busy)
        if not busy:
            self.download_button.setEnabled(bool(self.current_snapshot and self.current_snapshot.update_available))

    def _render_idle(self) -> None:
        preferences = self.service.load_preferences()
        detail = (
            f"Channel {preferences.channel} · every {preferences.check_interval_hours} hour(s) · "
            f"startup {'enabled' if preferences.check_on_startup else 'disabled'}"
        )
        self.summary.update_status("Update checks are idle", detail, tone="info")

    def _render(self, snapshot: UpdateCheckSnapshot) -> None:
        self.current_snapshot = snapshot
        tone = (
            "success"
            if snapshot.status in {"current", "available"}
            else "warning"
            if snapshot.status in {"deferred", "disabled"}
            else "error"
        )
        self.summary.update_status(
            snapshot.summary,
            (
                f"Current {snapshot.current_version} · latest {snapshot.latest_version or 'unknown'} · "
                f"{snapshot.channel} · rollout bucket {snapshot.rollout_bucket}/{snapshot.rollout_percentage}% · "
                f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status.title(),
                gate.label,
                gate.severity.title(),
                gate.detail,
                gate.remediation or "—",
            )
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.gate_table.resizeColumnsToContents()

        self.artifact_table.setRowCount(len(snapshot.artifacts))
        for row, artifact in enumerate(snapshot.artifacts):
            values = (
                "Yes" if snapshot.selected_artifact == artifact else "No",
                artifact.role.replace("_", " ").title(),
                artifact.filename,
                self._format_size(artifact.size_bytes),
                artifact.sha256,
                artifact.signature_status,
            )
            for column, value in enumerate(values):
                self.artifact_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.artifact_table.resizeColumnsToContents()
        self.release_notes.setPlainText(snapshot.release_notes)
        self.download_button.setEnabled(snapshot.update_available and not self.controller.busy)
        self.status_label.setText(f"Update check {snapshot.check_id}: {snapshot.status}")

    def open_download_folder(self) -> Path:
        folder = self.service.download_root
        folder.mkdir(parents=True, exist_ok=True)
        if callable(self.open_path):
            self.open_path(folder)
        self.status_label.setText(str(folder))
        return folder

    def copy_install_plan(self) -> dict[str, object]:
        snapshot = self.current_snapshot
        if snapshot is None:
            plan = {"allowed": False, "reason": "No update check is available.", "command": []}
        else:
            plan = self.service.install_plan(snapshot)
        command = " ".join(str(item) for item in plan.get("command", []))
        text = (
            f"Allowed: {plan.get('allowed', False)}\n"
            f"Reason: {plan.get('reason', '')}\n"
            f"Command: {command or 'none'}\n"
            "Automatic restart: disabled"
        )
        if callable(self.copy_path):
            self.copy_path(text)
        self.status_label.setText("Install plan copied. No installer was launched.")
        return plan

    def export_snapshot(self) -> Path | None:
        if self.current_snapshot is None:
            self.status_label.setText("No update snapshot is available to export.")
            return None
        path = self.service.export_snapshot(self.current_snapshot)
        self.status_label.setText(f"Exported {path.name}")
        return path

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"
