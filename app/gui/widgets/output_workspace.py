from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.audio_player import AudioPlayerWidget
from app.models.audio_player_state import AudioPlayerState
from app.services.audio_player_service import AudioPlayerService
from app.services.monitor_formatting import elide_middle


def format_file_size(size: int | float | None) -> str:
    value = max(0.0, float(size or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value):,} B"
    return f"{value:,.1f} {unit}"


class OutputPlaybackWorkspace(QWidget):
    """Professional output playback and file handoff workspace.

    The existing plain-text output log remains available through ``output_log``
    for compatibility. The workspace adds a persistent player, file metadata and
    direct handoff actions without changing generation or storage behavior.
    """

    def __init__(
        self,
        service: AudioPlayerService,
        output_log: QPlainTextEdit,
        *,
        open_path: Callable[[Path], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("outputPlaybackWorkspace")
        self.service = service
        self.output_log = output_log
        self.open_path = open_path
        self._current_path: Path | None = None
        self._build()
        self.service.state_changed.connect(self.render_state)
        self.render_state(self.service.state)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.header = QFrame()
        self.header.setObjectName("outputWorkspaceHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(10)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(2)
        self.title_label = QLabel("Output playback")
        self.title_label.setObjectName("outputWorkspaceTitle")
        self.subtitle_label = QLabel(
            "Review generated audio, verify the destination and hand files off without leaving the workspace."
        )
        self.subtitle_label.setObjectName("outputWorkspaceSubtitle")
        self.subtitle_label.setWordWrap(True)
        identity.addWidget(self.title_label)
        identity.addWidget(self.subtitle_label)

        self.status_badge = QLabel("No output loaded")
        self.status_badge.setObjectName("outputWorkspaceStatus")
        self.status_badge.setProperty("tone", "neutral")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumWidth(98)

        header_layout.addLayout(identity, 1)
        header_layout.addWidget(self.status_badge, 0, Qt.AlignTop)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        self.player_card = QFrame()
        self.player_card.setObjectName("outputPlayerCard")
        player_layout = QVBoxLayout(self.player_card)
        player_layout.setContentsMargins(10, 9, 10, 10)
        player_layout.setSpacing(7)
        player_title = QLabel("Player")
        player_title.setObjectName("outputSectionTitle")
        self.player = AudioPlayerWidget(
            self.service,
            open_folder=self._open_folder,
            parent=self.player_card,
        )
        player_layout.addWidget(player_title)
        player_layout.addWidget(self.player)
        body.addWidget(self.player_card, 3)

        self.file_card = QFrame()
        self.file_card.setObjectName("outputFileCard")
        file_layout = QVBoxLayout(self.file_card)
        file_layout.setContentsMargins(10, 9, 10, 10)
        file_layout.setSpacing(6)
        file_title = QLabel("File details")
        file_title.setObjectName("outputSectionTitle")
        self.path_label = QLabel("No generated file selected")
        self.path_label.setObjectName("outputFilePath")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.metadata_label = QLabel("Format — · Size —")
        self.metadata_label.setObjectName("outputFileMetadata")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        file_layout.addWidget(file_title)
        file_layout.addWidget(self.path_label)
        file_layout.addWidget(self.metadata_label)

        actions = QGridLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setHorizontalSpacing(7)
        actions.setVerticalSpacing(7)
        self.open_file_button = self._action_button(
            "Open file", "project.open", self.open_current_file, primary=True
        )
        self.open_folder_button = self._action_button(
            "Open folder", "project.output_folder", self.open_current_folder
        )
        self.copy_path_button = self._action_button(
            "Copy path", "general.copy", self.copy_current_path
        )
        self.copy_info_button = self._action_button(
            "Copy details", "report", self.copy_current_details
        )
        for index, button in enumerate(
            (
                self.open_file_button,
                self.open_folder_button,
                self.copy_path_button,
                self.copy_info_button,
            )
        ):
            actions.addWidget(button, index // 2, index % 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        file_layout.addLayout(actions)
        file_layout.addStretch(1)
        body.addWidget(self.file_card, 2)
        root.addLayout(body)

        log_header = QFrame()
        log_header.setObjectName("outputLogHeader")
        log_header_layout = QHBoxLayout(log_header)
        log_header_layout.setContentsMargins(10, 5, 10, 5)
        log_header_layout.setSpacing(8)
        log_title = QLabel("Output activity")
        log_title.setObjectName("outputSectionTitle")
        self.clear_log_button = QPushButton("Clear log")
        self.clear_log_button.setObjectName("outputQuietAction")
        self.clear_log_button.setIcon(action_icon("general.clear"))
        self.clear_log_button.clicked.connect(self.output_log.clear)
        log_header_layout.addWidget(log_title)
        log_header_layout.addStretch(1)
        log_header_layout.addWidget(self.clear_log_button)
        root.addWidget(log_header)

        self.output_log.setObjectName("outputActivityLog")
        self.output_log.setPlaceholderText("Generated output paths and handoff messages appear here.")
        self.output_log.setMinimumHeight(64)
        root.addWidget(self.output_log, 1)
        self.output_log.show()

    def _action_button(
        self,
        text: str,
        icon_name: str,
        handler: Callable[[], None],
        *,
        primary: bool = False,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("outputFileAction")
        button.setProperty("primary", primary)
        button.setIcon(action_icon(icon_name))
        button.setMinimumHeight(32)
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(handler)
        return button

    @property
    def current_path(self) -> Path | None:
        return self._current_path or self.service.current_path

    def load_output(self, path: Path | str, *, autoplay: bool = False) -> AudioPlayerState:
        target = Path(path)
        self._current_path = target
        state = self.player.load(target)
        self._render_file(target)
        if autoplay and state.loaded:
            state = self.service.play()
        return state

    def set_output_context(self, path: Path | str | None) -> None:
        self._current_path = Path(path) if path else None
        self._render_file(self._current_path)
        self._sync_file_actions()

    def render_state(self, state: AudioPlayerState) -> None:
        if state.current_path:
            self._current_path = state.current_path
            self._render_file(state.current_path)
        tone = "error" if state.error else {
            "playing": "running",
            "paused": "warning",
            "stopped": "success" if state.loaded else "neutral",
        }.get(state.playback_state, "neutral")
        text = state.error or state.status or "Ready"
        self.status_badge.setText(text)
        self.status_badge.setToolTip(text)
        self.status_badge.setProperty("tone", tone)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self._sync_file_actions()

    def _sync_file_actions(self) -> None:
        """Keep file handoff actions aligned with the selected output context.

        Output context can be supplied without loading the file into the audio
        backend. In that case the path, metadata and handoff actions must still
        become available immediately instead of waiting for a playback state
        change.
        """

        enabled = self.current_path is not None
        for button in (
            self.open_file_button,
            self.open_folder_button,
            self.copy_path_button,
            self.copy_info_button,
        ):
            button.setEnabled(enabled)

    def _render_file(self, path: Path | None) -> None:
        if path is None:
            self.path_label.setText("No generated file selected")
            self.path_label.setToolTip("")
            self.metadata_label.setText("Format — · Size —")
            return
        full = str(path)
        self.path_label.setText(elide_middle(full, 74))
        self.path_label.setToolTip(full)
        suffix = path.suffix.lstrip(".").upper() or "File"
        if path.exists() and path.is_file():
            try:
                size = format_file_size(path.stat().st_size)
            except OSError:
                size = "Unavailable"
            state = "Ready"
        else:
            size = "Missing"
            state = "File not found"
        self.metadata_label.setText(f"{suffix} · {size} · {state}")

    def _open_folder(self, path: Path) -> None:
        if self.open_path:
            self.open_path(path)

    def open_current_file(self) -> None:
        path = self.current_path
        if path and self.open_path:
            self.open_path(path if path.exists() else path.parent)

    def open_current_folder(self) -> None:
        path = self.current_path
        if path and self.open_path:
            self.open_path(path.parent)

    def copy_current_path(self) -> None:
        path = self.current_path
        if path:
            QApplication.clipboard().setText(str(path))

    def copy_current_details(self) -> None:
        path = self.current_path
        if path:
            QApplication.clipboard().setText(
                f"Output: {path}\n{self.metadata_label.text()}"
            )
