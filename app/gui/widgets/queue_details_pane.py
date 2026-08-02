from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from app.gui.icons import icon


class QueueDetailsPane:
    """Build and own the selected queue-row inspector independently of MainWindow.

    The pane is intentionally optimized for the narrow inspector dock: important
    identity and status stay at the top, verbose request metadata wraps inside
    dedicated cards, and actions use a two-column grid so no button is clipped.
    """

    def __init__(
        self,
        host,
        *,
        play_output: Callable[[], None],
        open_output: Callable[[], None],
        stop_playback: Callable[[], None],
        copy_output: Callable[[], None],
    ) -> None:
        root = QVBoxLayout(host)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = QFrame()
        header.setObjectName("queueInspectorHeader")
        self.header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(3)
        self.pname = QLabel("No row selected")
        self.pname.setObjectName("queueInspectorTitle")
        self.pname.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pname.setWordWrap(True)
        self.pmeta = QLabel("Load a source and select a row to inspect it.")
        self.pmeta.setObjectName("queueInspectorMeta")
        self.pmeta.setWordWrap(True)
        self.pmeta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        identity.addWidget(self.pname)
        identity.addWidget(self.pmeta)

        self.pstatus = QLabel("")
        self.pstatus.setObjectName("queueInspectorStatus")
        self.pstatus.setAlignment(Qt.AlignCenter)
        self.pstatus.setMinimumWidth(78)
        self.pstatus.setMaximumWidth(112)
        self.pstatus.setProperty("tone", "neutral")

        header_layout.addLayout(identity, 1)
        header_layout.addWidget(self.pstatus, 0, Qt.AlignTop)
        root.addWidget(header)

        request_card = QFrame()
        request_card.setObjectName("queueInspectorCard")
        self.request_card = request_card
        request_layout = QVBoxLayout(request_card)
        request_layout.setContentsMargins(12, 10, 12, 10)
        request_layout.setSpacing(6)
        request_title = QLabel("Resolved request")
        request_title.setObjectName("queueInspectorSectionTitle")
        self.presolved = QLabel("Resolved request: —")
        self.presolved.setObjectName("queueInspectorDetail")
        self.presolved.setWordWrap(True)
        self.presolved.setTextInteractionFlags(Qt.TextSelectableByMouse)
        output_title = QLabel("Output destination")
        output_title.setObjectName("queueInspectorSectionTitle")
        self.poutput = QLabel("")
        self.poutput.setObjectName("queueInspectorDetail")
        self.poutput.setWordWrap(True)
        self.poutput.setTextInteractionFlags(Qt.TextSelectableByMouse)
        request_layout.addWidget(request_title)
        request_layout.addWidget(self.presolved)
        request_layout.addSpacing(3)
        request_layout.addWidget(output_title)
        request_layout.addWidget(self.poutput)
        root.addWidget(request_card)

        self.pretry = QPlainTextEdit()
        self.pretry.setObjectName("queueRetryHistory")
        self.pretry.setReadOnly(True)
        self.pretry.setMaximumHeight(120)
        self.pretry.setPlaceholderText("Retry history: —")
        self.pretry.hide()
        root.addWidget(self.pretry)

        text_card = QFrame()
        text_card.setObjectName("queueInspectorCard")
        self.text_card = text_card
        text_layout = QVBoxLayout(text_card)
        text_layout.setContentsMargins(10, 9, 10, 10)
        text_layout.setSpacing(6)
        text_title = QLabel("Source text")
        text_title.setObjectName("queueInspectorSectionTitle")
        self.ptext = QPlainTextEdit()
        self.ptext.setObjectName("queueDetailsText")
        self.ptext.setReadOnly(True)
        self.ptext.setMinimumHeight(180)
        self.ptext.setPlaceholderText("Select a queue row to preview its text.")
        text_layout.addWidget(text_title)
        text_layout.addWidget(self.ptext, 1)
        root.addWidget(text_card, 1)

        action_card = QFrame()
        action_card.setObjectName("queueInspectorActions")
        self.action_card = action_card
        actions = QGridLayout(action_card)
        actions.setContentsMargins(8, 8, 8, 8)
        actions.setHorizontalSpacing(7)
        actions.setVerticalSpacing(7)

        self.play_output_button = QPushButton("Play")
        self.play_output_button.setIcon(icon("play"))
        self.play_output_button.setProperty("primary", True)
        self.open_selected_button = QPushButton("Open")
        self.open_selected_button.setIcon(icon("folder"))
        self.copy_output_button = QPushButton("Copy path")
        self.copy_output_button.setIcon(icon("copy"))
        self.stop_playback_button = QPushButton("Stop audio")
        self.stop_playback_button.setIcon(icon("stop"))

        self.play_output_button.clicked.connect(play_output)
        self.open_selected_button.clicked.connect(open_output)
        self.stop_playback_button.clicked.connect(stop_playback)
        self.copy_output_button.clicked.connect(copy_output)

        buttons = (
            self.play_output_button,
            self.open_selected_button,
            self.copy_output_button,
            self.stop_playback_button,
        )
        for index, button in enumerate(buttons):
            button.setObjectName("queueInspectorAction")
            button.setMinimumWidth(0)
            button.setMinimumHeight(34)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            actions.addWidget(button, index // 2, index % 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        root.addWidget(action_card)

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        compact = value == "compact"
        for card in (self.header, self.request_card, self.text_card, self.action_card):
            card.setProperty("responsiveMode", value)
        self.pmeta.setVisible(not compact)
        self.pstatus.setMaximumWidth(96 if compact else 112)
        self.ptext.setMinimumHeight(180)
        self.copy_output_button.setText("Copy" if compact else "Copy path")
        self.stop_playback_button.setText("Stop" if compact else "Stop audio")
        for card in (self.header, self.request_card, self.text_card, self.action_card):
            card.style().unpolish(card)
            card.style().polish(card)
