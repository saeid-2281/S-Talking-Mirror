from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover - depends on frozen host multimedia backend
    QAudioOutput = None
    QMediaPlayer = None

from app.models.audio_player_state import AudioPlayerState


class AudioPlayerService(QObject):
    """Shared application audio player; only one file can play at a time."""

    state_changed = Signal(object)
    _shared_instance: "AudioPlayerService | None" = None

    def __new__(cls, *args: object, **kwargs: object) -> "AudioPlayerService":
        if cls._shared_instance is None:
            cls._shared_instance = super().__new__(cls)
        return cls._shared_instance

    def __init__(self, parent: QObject | None = None) -> None:
        if getattr(self, "_initialized", False):
            return
        super().__init__(parent)
        self.available = QAudioOutput is not None and QMediaPlayer is not None
        if not self.available:
            self.audio_output = None
            self.player = None
            self._state = AudioPlayerState(status="Audio playback unavailable", error="Qt Multimedia is unavailable.")
            self._initialized = True
            return
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.7)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self._state = AudioPlayerState()
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._error_changed)
        self._initialized = True

    @property
    def current_path(self) -> Path | None:
        return self._state.current_path

    @property
    def position(self) -> int:
        return self._state.position

    @property
    def duration(self) -> int:
        return self._state.duration

    @property
    def playback_state(self) -> str:
        return self._state.playback_state

    @property
    def error_state(self) -> str:
        return self._state.error

    @property
    def state(self) -> AudioPlayerState:
        return self._state

    def load(self, path: Path | str) -> AudioPlayerState:
        target = Path(path)
        self.stop()
        if not self.available:
            return self._publish(AudioPlayerState(current_path=target, status="Audio playback unavailable", error="Qt Multimedia is unavailable."))
        if not target.exists() or not target.is_file():
            return self._publish(
                AudioPlayerState(
                    current_path=target,
                    volume=self._state.volume,
                    status="Audio file is missing.",
                    error=f"File does not exist: {target}",
                )
            )
        self.player.setSource(QUrl.fromLocalFile(str(target)))
        return self._publish(
            AudioPlayerState(
                current_path=target,
                volume=self._state.volume,
                status="Loaded",
                loaded=True,
            )
        )

    def play(self) -> AudioPlayerState:
        if not self.available:
            return self._publish(self._copy(playback_state="stopped", status="Audio playback unavailable", error="Qt Multimedia is unavailable."))
        if not self._state.loaded or self._state.current_path is None:
            return self._publish(self._copy(status="No audio loaded.", error=""))
        self.player.play()
        return self._publish(self._copy(playback_state="playing", status="Playing"))

    def pause(self) -> AudioPlayerState:
        if not self.available:
            return self._publish(self._copy(playback_state="stopped", status="Audio playback unavailable"))
        self.player.pause()
        return self._publish(self._copy(playback_state="paused", status="Paused"))

    def stop(self) -> AudioPlayerState:
        if not self.available:
            return self._publish(self._copy(playback_state="stopped", position=0, status="Audio playback unavailable"))
        self.player.stop()
        return self._publish(self._copy(playback_state="stopped", position=0, status="Stopped"))

    def unload(self) -> AudioPlayerState:
        """Stop playback and release the native media source/file handle."""

        volume = self._state.volume
        if self.available:
            self.player.stop()
            self.player.setSource(QUrl())
        return self._publish(AudioPlayerState(volume=volume))

    def seek(self, milliseconds: int) -> AudioPlayerState:
        position = max(0, int(milliseconds))
        if not self.available:
            return self._publish(self._copy(position=position, status="Audio playback unavailable"))
        self.player.setPosition(position)
        return self._publish(self._copy(position=position))

    def set_volume(self, value: int) -> AudioPlayerState:
        volume = max(0, min(100, int(value)))
        if not self.available:
            return self._publish(self._copy(volume=volume, status="Audio playback unavailable"))
        self.audio_output.setVolume(volume / 100)
        return self._publish(self._copy(volume=volume))

    def _position_changed(self, position: int) -> None:
        self._publish(self._copy(position=position))

    def _duration_changed(self, duration: int) -> None:
        self._publish(self._copy(duration=duration))

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        mapping = {
            QMediaPlayer.PlaybackState.PlayingState: ("playing", "Playing"),
            QMediaPlayer.PlaybackState.PausedState: ("paused", "Paused"),
            QMediaPlayer.PlaybackState.StoppedState: ("stopped", "Stopped"),
        }
        playback, status = mapping.get(state, ("stopped", "Stopped"))
        self._publish(self._copy(playback_state=playback, status=status))

    def _error_changed(self, _error: QMediaPlayer.Error, message: str) -> None:
        if message:
            self._publish(self._copy(playback_state="stopped", status="Playback error", error=message))

    def _copy(self, **updates: object) -> AudioPlayerState:
        data = self._state.__dict__.copy()
        data.update(updates)
        return AudioPlayerState(**data)

    def _publish(self, state: AudioPlayerState) -> AudioPlayerState:
        self._state = state
        self.state_changed.emit(state)
        return state
