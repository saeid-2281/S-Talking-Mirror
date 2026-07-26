from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

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
        self.service = service
        self.open_folder = open_folder
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        self.service.state_changed.connect(self.render)
        self.render(self.service.state)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.filename = QLabel("No file loaded")
        self.filename.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.filename)
        controls = QHBoxLayout()
        self.play_pause = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.play_pause.setMinimumWidth(72)
        self.stop_button.setMinimumWidth(72)
        self.play_pause.clicked.connect(self.toggle_play_pause)
        self.stop_button.clicked.connect(self.service.stop)
        controls.addWidget(self.play_pause)
        controls.addWidget(self.stop_button)
        root.addLayout(controls)
        seek = QHBoxLayout()
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.service.seek)
        self.time_label = QLabel("0:00 / 0:00")
        seek.addWidget(self.seek_slider, 1)
        seek.addWidget(self.time_label)
        root.addLayout(seek)
        volume = QHBoxLayout()
        volume.addWidget(QLabel("Volume"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(self.service.set_volume)
        volume.addWidget(self.volume_slider, 1)
        root.addLayout(volume)
        actions = QHBoxLayout()
        self.open_folder_button = QPushButton("Open folder")
        self.copy_path_button = QPushButton("Copy path")
        self.open_folder_button.setMinimumWidth(92)
        self.copy_path_button.setMinimumWidth(86)
        self.open_folder_button.clicked.connect(self.open_current_folder)
        self.copy_path_button.clicked.connect(self.copy_current_path)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.copy_path_button)
        root.addLayout(actions)
        self.status = QLabel("No audio loaded")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.status)

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
        self.play_pause.setText("Pause" if state.playback_state == "playing" else "Play")
        self.status.setText(state.error or state.status)
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
