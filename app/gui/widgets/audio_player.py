from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import icon
from app.models.audio_player_state import AudioPlayerState
from app.services.audio_player_service import AudioPlayerService
from app.services.monitor_formatting import elide_middle


def format_audio_time(milliseconds: int | float | None) -> str:
    total = max(0, int((milliseconds or 0) / 1000))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class AudioPlayerWidget(QWidget):
    def __init__(
        self,
        service: AudioPlayerService,
        *,
        open_folder: Callable[[Path], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("audioPlayerWidget")
        self.service = service
        self.open_folder = open_folder
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        self.service.state_changed.connect(self.render)
        self.render(self.service.state)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        header = QFrame()
        header.setObjectName("audioPlayerHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(9, 6, 9, 6)
        header_layout.setSpacing(8)
        self.filename = QLabel("No file loaded")
        self.filename.setObjectName("audioPlayerFilename")
        self.filename.setWordWrap(True)
        self.filename.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status = QLabel("No audio loaded")
        self.status.setObjectName("audioPlayerStatus")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setProperty("tone", "neutral")
        header_layout.addWidget(self.filename, 1)
        header_layout.addWidget(self.status)
        root.addWidget(header)

        transport = QFrame()
        transport.setObjectName("audioTransportBar")
        controls = QGridLayout(transport)
        controls.setContentsMargins(9, 8, 9, 8)
        controls.setHorizontalSpacing(8)
        controls.setVerticalSpacing(7)
        self.play_pause = QPushButton("Play")
        self.play_pause.setObjectName("audioPrimaryAction")
        self.play_pause.setIcon(icon("play"))
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("audioStopAction")
        self.stop_button.setIcon(icon("stop"))
        self.play_pause.setMinimumWidth(82)
        self.stop_button.setMinimumWidth(78)
        self.play_pause.clicked.connect(self.toggle_play_pause)
        self.stop_button.clicked.connect(self.service.stop)
        controls.addWidget(self.play_pause, 0, 0)
        controls.addWidget(self.stop_button, 0, 1)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setObjectName("audioSeekSlider")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.service.seek)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("audioTimeLabel")
        controls.addWidget(self.seek_slider, 1, 0, 1, 2)
        controls.addWidget(self.time_label, 1, 2)

        volume_label = QLabel("Volume")
        volume_label.setObjectName("audioControlLabel")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("audioVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(self.service.set_volume)
        controls.addWidget(volume_label, 2, 0)
        controls.addWidget(self.volume_slider, 2, 1, 1, 2)
        controls.setColumnStretch(1, 1)
        root.addWidget(transport)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(7)
        self.open_folder_button = QPushButton("Open folder")
        self.open_folder_button.setIcon(icon("folder"))
        self.copy_path_button = QPushButton("Copy path")
        self.copy_path_button.setIcon(icon("copy"))
        self.open_folder_button.setMinimumWidth(92)
        self.copy_path_button.setMinimumWidth(86)
        self.open_folder_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.copy_path_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.open_folder_button.clicked.connect(self.open_current_folder)
        self.copy_path_button.clicked.connect(self.copy_current_path)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.copy_path_button)
        root.addLayout(actions)

    def load(self, path: Path | str) -> AudioPlayerState:
        return self.service.load(path)

    def toggle_play_pause(self) -> None:
        if self.service.playback_state == "playing":
            self.service.pause()
        else:
            self.service.play()

    def render(self, state: AudioPlayerState) -> None:
        path_text = str(state.current_path) if state.current_path else ""
        self.filename.setText(elide_middle(path_text or state.filename, 58))
        self.filename.setToolTip(path_text)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setRange(0, max(0, state.duration))
        self.seek_slider.setValue(max(0, min(state.position, state.duration)))
        self.seek_slider.blockSignals(False)
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(state.volume)
        self.volume_slider.blockSignals(False)
        self.time_label.setText(f"{format_audio_time(state.position)} / {format_audio_time(state.duration)}")
        playing = state.playback_state == "playing"
        self.play_pause.setText("Pause" if playing else "Play")
        self.play_pause.setIcon(icon("pause" if playing else "play"))
        self.status.setText(state.error or state.status)
        tone = "error" if state.error else {
            "playing": "running",
            "paused": "warning",
            "stopped": "success" if state.loaded else "neutral",
        }.get(state.playback_state, "neutral")
        self.status.setProperty("tone", tone)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        for widget in (self.play_pause, self.stop_button, self.seek_slider, self.open_folder_button, self.copy_path_button):
            widget.setEnabled(state.loaded)

    def open_current_folder(self) -> None:
        path = self.service.current_path
        if path and self.open_folder:
            self.open_folder(path.parent)

    def copy_current_path(self) -> None:
        path = self.service.current_path
        if path:
            QApplication.clipboard().setText(str(path))

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
            return
        super().keyPressEvent(event)
