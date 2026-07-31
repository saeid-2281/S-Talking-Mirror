from __future__ import annotations

from app.gui.widgets.audio_player import AudioPlayerWidget, format_audio_time
from app.gui.widgets.numeric_spinbox import ControlledDoubleSpinBox, ControlledSpinBox
from app.gui.widgets.preview_waveform import PreviewWaveformWidget
from app.gui.widgets.queue_table_model import QueueColumn, QueueDataRole, QueueTableModel
from app.gui.widgets.queue_table_view import QueueTableView
from app.gui.widgets.queue_view_adapter import QueueViewAdapter
from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.gui.widgets.voice_table_model import VoiceDataRole, VoiceTableModel
from app.gui.widgets.voice_table_view import VoiceTableView

__all__ = [
    "AudioPlayerWidget",
    "ControlledDoubleSpinBox",
    "ControlledSpinBox",
    "PreviewWaveformWidget",
    "QueueColumn",
    "QueueDataRole",
    "QueueTableModel",
    "QueueTableView",
    "QueueViewAdapter",
    "TextStudioWorkspace",
    "VoiceDataRole",
    "VoiceTableModel",
    "VoiceTableView",
    "format_audio_time",
]

