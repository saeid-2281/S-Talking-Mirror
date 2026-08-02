from __future__ import annotations

from app.gui.widgets.batch_plan_summary import BatchPlanSummary, PlanMetricCard

from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.gui.widgets.audio_player import AudioPlayerWidget, format_audio_time
from app.gui.widgets.numeric_spinbox import ControlledDoubleSpinBox, ControlledSpinBox
from app.gui.widgets.output_workspace import OutputPlaybackWorkspace, format_file_size
from app.gui.widgets.preview_waveform import PreviewWaveformWidget
from app.gui.widgets.provider_controls import ProviderCapabilityBadge, ProviderOverviewCard
from app.gui.widgets.professional_components import (
    DialogHeader,
    EmptyStateCard,
    InlineFeedbackBar,
    LiveStatusAnnouncer,
    PreferencePreview,
)
from app.gui.widgets.queue_table_model import QueueColumn, QueueDataRole, QueueTableModel
from app.gui.widgets.queue_table_view import QueueTableView
from app.gui.widgets.queue_view_adapter import QueueViewAdapter
from app.gui.widgets.text_studio_workspace import TextStudioWorkspace
from app.gui.widgets.text_studio_quality import TextStudioQualityPanel
from app.gui.widgets.voice_table_model import VoiceDataRole, VoiceTableModel
from app.gui.widgets.voice_table_view import VoiceTableView

__all__ = [
    "BatchPlanSummary",
    "PlanMetricCard",
    "DialogWorkspace",
    "DialogSection",
    "DialogStatusCard",
    "AudioPlayerWidget",
    "ControlledDoubleSpinBox",
    "ControlledSpinBox",
    "DialogHeader",
    "EmptyStateCard",
    "InlineFeedbackBar",
    "LiveStatusAnnouncer",
    "OutputPlaybackWorkspace",
    "PreferencePreview",
    "PreviewWaveformWidget",
    "ProviderCapabilityBadge",
    "ProviderOverviewCard",
    "QueueColumn",
    "QueueDataRole",
    "QueueTableModel",
    "QueueTableView",
    "QueueViewAdapter",
    "TextStudioWorkspace",
    "TextStudioQualityPanel",
    "VoiceDataRole",
    "VoiceTableModel",
    "VoiceTableView",
    "format_audio_time",
    "format_file_size",
]

