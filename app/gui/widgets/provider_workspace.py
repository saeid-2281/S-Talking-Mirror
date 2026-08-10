"""Provider workspace composition for the v0.19 product UI rewrite.

This module owns the visual construction of provider controls so MainWindow no
longer carries a monolithic, hard-to-maintain block of form code.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.design_system import COMPACT, SPACING
from app.gui.icons import action_icon, icon
from app.gui.widgets import ControlledDoubleSpinBox, ControlledSpinBox
from app.gui.widgets.provider_controls import ProviderOverviewCard, ProviderSection
from app.gui.widgets.provider_intelligence import ProviderIntelligenceCard
from app.gui.widgets.smart_provider_routing import SmartProviderRoutingCard
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY


class IconActionButton(QPushButton):
    """Compact action button that keeps a logical text for tests/accessibility."""

    def __init__(self, logical_text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.logical_text = logical_text
        self.setIcon(action_icon(icon_name))
        self.setToolTip(logical_text)
        self.setAccessibleName(logical_text)
        self.setFixedSize(COMPACT.icon_button, COMPACT.icon_button)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def text(self) -> str:  # compatibility with existing tests
        return self.logical_text or super().text()


class ProviderConnectionButton(QPushButton):
    """Stable two-line provider status surface."""

    HEIGHT = 52

    def __init__(self, text: str = "Not tested", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("connectionStatus")
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFlat(False)
        self.setIcon(action_icon("general.info"))
        self.setToolTip("Connection has not been tested. Click for account details.")
        self.setAccessibleName("Provider connection status: Not tested")

    def minimumHeight(self) -> int:  # keep QSS from changing test-visible geometry
        return self.HEIGHT

    def maximumHeight(self) -> int:
        return self.HEIGHT


@dataclass(frozen=True)
class ProviderWorkspaceResult:
    panel: QFrame
    scroll_area: QScrollArea
    sections: dict[str, ProviderSection]


class ProviderWorkspaceBuilder:
    """Builds the provider panel while preserving MainWindow's public attributes."""

    PROVIDERS = list(DEFAULT_PROVIDER_REGISTRY.provider_ids())

    def __init__(self, owner) -> None:
        self.owner = owner

    @staticmethod
    def _inline_row(editor: QWidget, action: QWidget | None = None) -> QFrame:
        row = QFrame()
        row.setObjectName("inlineFieldRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["sm"])
        layout.addWidget(editor, 1)
        if action is not None:
            layout.addWidget(action, 0, Qt.AlignTop)
        return row

    @staticmethod
    def _prepare_editor(widget: QWidget, popup_width: int | None = None) -> None:
        widget.setMinimumWidth(180)
        widget.setMinimumHeight(COMPACT.control_height)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if isinstance(widget, QComboBox):
            widget.view().setMinimumWidth(popup_width or 300)
            widget.setToolTip(widget.currentText())
            widget.currentTextChanged.connect(widget.setToolTip)

    def build(self) -> ProviderWorkspaceResult:
        owner = self.owner

        panel = QFrame()
        panel.setObjectName("providerPanel")
        panel.setMinimumWidth(270)
        panel.setMaximumWidth(340)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        root = QVBoxLayout(panel)
        root.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        root.setSpacing(SPACING["sm"])

        header = QFrame()
        header.setObjectName("providerPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        header_layout.setSpacing(SPACING["sm"])
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title = QLabel("Voice provider")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Account, voice and output settings")
        subtitle.setObjectName("panelSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)

        owner.account_manager_button = IconActionButton("Provider accounts", "provider.accounts")
        owner.account_manager_button.clicked.connect(owner.open_provider_accounts)
        header_layout.addWidget(owner.account_manager_button)
        root.addWidget(header)

        owner.provider_overview = ProviderOverviewCard()
        root.addWidget(owner.provider_overview)

        owner.provider_intelligence = ProviderIntelligenceCard()
        owner.provider_intelligence.actionRequested.connect(
            owner.handle_provider_intelligence_action
        )
        root.addWidget(owner.provider_intelligence)

        owner.smart_provider_routing = SmartProviderRoutingCard()
        owner.smart_provider_routing.actionRequested.connect(
            owner.handle_smart_provider_routing_action
        )
        owner.smart_provider_routing.preferenceChanged.connect(
            owner.smart_provider_routing_preference_changed
        )
        root.addWidget(owner.smart_provider_routing)

        owner.provider = QComboBox()
        owner.provider.addItems(owner.context.provider_catalog_service.provider_ids())
        owner.provider.setToolTip(
            "Select the synthesis provider. Display names and readiness remain available in status and diagnostics."
        )

        owner.api_profile = QComboBox()
        owner.refresh_api_profiles()
        owner.api_profile.currentIndexChanged.connect(owner.api_profile_changed)

        owner.failover = QComboBox()
        owner.failover.addItem("Never", "never")
        owner.failover.addItem("Pause and ask", "pause")
        owner.failover.addItem("Automatic", "auto")

        owner.key = QLineEdit()
        owner.key.setEchoMode(QLineEdit.Password)
        owner.test_connection_button = IconActionButton("Test connection", "provider.test_connection")
        owner.test_connection_button.clicked.connect(owner.test_elevenlabs_connection)
        owner.connection_status = ProviderConnectionButton("Not tested")
        owner.connection_status.clicked.connect(owner.open_account_details)

        owner.voice = QLineEdit()
        owner.voice_browser_button = IconActionButton("Browse voices", "provider.browse_voices")
        owner.voice_browser_button.clicked.connect(owner.open_voice_browser)

        owner.model = QComboBox()
        owner.model.setEditable(False)
        owner.model.addItem("Eleven Multilingual v2", "eleven_multilingual_v2")
        owner.model.addItem("Mock / local default", "piper-local")
        owner.refresh_models_button = IconActionButton("Refresh models", "provider.refresh_models")
        owner.refresh_models_button.clicked.connect(owner.refresh_models)

        owner.language = QComboBox()
        owner.populate_language_dropdown()
        owner.language.setToolTip(
            "Source language for generation and previews when explicit language control is supported."
        )

        owner.piper = QLineEdit()
        owner.piper_model_button = IconActionButton("Browse Piper model", "project.output_folder")
        owner.piper_model_button.clicked.connect(owner.pick_piper)

        for combo in [owner.provider, owner.api_profile, owner.model, owner.language, owner.failover]:
            self._prepare_editor(combo)
        owner.failover.view().setMinimumWidth(220)
        for field in [owner.key, owner.voice, owner.piper]:
            self._prepare_editor(field)

        owner.stability = owner.slider(45)
        owner.similarity = owner.slider(75)
        owner.style = owner.slider(20)
        owner.speed = ControlledDoubleSpinBox()
        owner.speed.setRange(0.7, 1.2)
        owner.speed.setDecimals(2)
        owner.speed.setSingleStep(0.05)
        owner.speed.setSuffix("×")
        owner.speed.setValue(1)
        owner.delay = ControlledDoubleSpinBox()
        owner.delay.setRange(0, 60)
        owner.delay.setDecimals(1)
        owner.delay.setSingleStep(0.1)
        owner.delay.setSuffix(" s")
        owner.delay.setValue(0.5)
        owner.retries = ControlledSpinBox()
        owner.retries.setRange(0, 10)
        owner.retries.setValue(4)
        owner.boost = QCheckBox("Speaker boost")
        owner.boost.setChecked(True)
        owner.pronunciation_aid = QCheckBox("Use pronunciation dictionary")
        owner.pronunciation_aid.setChecked(True)
        owner.pronunciation_aid.setToolTip(
            "Uses provider language and dictionary metadata without changing the spoken text."
        )
        owner.skip = QCheckBox("Skip existing output")
        owner.skip.setChecked(True)

        owner.restore_defaults_button = QPushButton("Restore provider defaults")
        owner.restore_defaults_button.setIcon(icon("settings"))
        owner.restore_defaults_button.clicked.connect(owner.restore_defaults)

        profile_row = self._inline_row(owner.api_profile)
        key_row = self._inline_row(owner.key, owner.test_connection_button)
        voice_row = self._inline_row(owner.voice, owner.voice_browser_button)
        model_row = self._inline_row(owner.model, owner.refresh_models_button)
        piper_row = self._inline_row(owner.piper, owner.piper_model_button)

        owner.provider_sections = {
            "Provider & Account": ProviderSection(
                "Provider & Account",
                "Account",
                True,
                "Choose the synthesis engine and the credential profile used for this project.",
            ),
            "Voice & Model": ProviderSection(
                "Voice & Model",
                "Voice/model",
                True,
                "Select the speaking voice, model and source language for generated audio.",
            ),
            "Audio Settings": ProviderSection(
                "Audio Settings",
                "Speed 1.00×",
                False,
                "Tune provider-specific expression controls and pacing.",
            ),
            "Pronunciation": ProviderSection(
                "Pronunciation",
                "Project dictionary",
                False,
                "Apply the active pronunciation dictionary without modifying source text.",
            ),
            "Advanced": ProviderSection(
                "Advanced",
                "Retry 4 · Skip existing",
                False,
                "Control failover, retries and output-protection behavior.",
            ),
        }
        for section in owner.provider_sections.values():
            root.addWidget(section)

        owner.provider_field_rows = {}

        def add_field(section_name: str, key: str, label: str, widget: QWidget):
            field = owner.provider_sections[section_name].addRow(label, widget)
            owner.provider_field_rows[key] = field
            return field

        add_field("Provider & Account", "provider", "Provider", owner.provider)
        add_field("Provider & Account", "api_profile", "API profile", profile_row)
        add_field("Provider & Account", "api_key", "API key", key_row)
        add_field("Provider & Account", "connection", "Connection", owner.connection_status)

        add_field("Voice & Model", "voice", "Voice", voice_row)
        add_field("Voice & Model", "model", "Model", model_row)
        add_field("Voice & Model", "language", "Language", owner.language)
        add_field("Voice & Model", "piper", "Piper model", piper_row)

        for key, label, widget in [
            ("stability", "Stability", owner.stability),
            ("similarity", "Similarity", owner.similarity),
            ("style", "Style", owner.style),
            ("speed", "Speed", owner.speed),
            ("delay", "Delay", owner.delay),
        ]:
            add_field("Audio Settings", key, label, widget)

        add_field("Pronunciation", "pronunciation", "Dictionary", owner.pronunciation_aid)
        add_field("Advanced", "failover", "Failover", owner.failover)
        add_field("Advanced", "retries", "Retries", owner.retries)
        add_field("Advanced", "boost", "", owner.boost)
        add_field("Advanced", "skip", "", owner.skip)
        add_field("Advanced", "restore_defaults", "", owner.restore_defaults_button)

        root.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("providerScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)

        owner.provider_panel = panel
        owner.provider_scroll = scroll
        return ProviderWorkspaceResult(panel, scroll, owner.provider_sections)
