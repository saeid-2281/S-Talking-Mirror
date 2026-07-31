from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QWidget


class PreviewWaveformWidget(QWidget):
    """Lightweight deterministic preview visualization.

    This is intentionally not a decoder. It renders a stable waveform-like
    summary from the cached audio bytes, so it works without additional audio
    analysis dependencies and never blocks the GUI on media probing.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: tuple[float, ...] = ()
        self.setObjectName("previewWaveform")
        self.setMinimumHeight(54)
        self.setMaximumHeight(76)
        self.setToolTip("Visual summary of the current cached preview")

    @property
    def samples(self) -> tuple[float, ...]:
        return self._samples

    def clear(self) -> None:
        self._samples = ()
        self.update()

    def set_path(self, path: Path | str | None) -> None:
        if path is None:
            self.clear()
            return
        target = Path(path)
        if not target.exists() or not target.is_file():
            self.clear()
            return
        try:
            payload = target.read_bytes()
        except OSError:
            self.clear()
            return
        if not payload:
            self.clear()
            return

        bar_count = 64
        step = max(1, len(payload) // bar_count)
        values: list[float] = []
        for offset in range(0, len(payload), step):
            chunk = payload[offset : offset + step]
            if not chunk:
                continue
            centered = [abs(value - 128) / 128 for value in chunk]
            values.append(max(0.08, min(1.0, sum(centered) / len(centered))))
            if len(values) >= bar_count:
                break
        self._samples = tuple(values)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        palette = self.palette()
        base = palette.color(QPalette.Base)
        accent = palette.color(QPalette.Highlight)
        muted = palette.color(QPalette.Mid)

        painter.setPen(Qt.NoPen)
        painter.setBrush(base)
        painter.drawRoundedRect(rect, 8, 8)

        if not self._samples:
            painter.setPen(muted)
            painter.drawText(rect, Qt.AlignCenter, "No preview waveform")
            return

        width = max(1.0, rect.width() / len(self._samples))
        center = rect.center().y()
        painter.setBrush(QColor(accent))
        for index, value in enumerate(self._samples):
            height = max(3.0, rect.height() * value)
            x = rect.left() + index * width
            painter.drawRoundedRect(
                int(x),
                int(center - height / 2),
                max(1, int(width * 0.62)),
                int(height),
                1,
                1,
            )
