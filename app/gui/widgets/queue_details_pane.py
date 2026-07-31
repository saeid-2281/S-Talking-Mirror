from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout

from app.gui.icons import icon


class QueueDetailsPane:
    """Build and own the selected queue-row inspector independently of MainWindow."""

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
        root.setSpacing(7)

        self.pname = QLabel("No row selected")
        self.pname.setObjectName("previewTitle")
        self.pstatus = QLabel("")
        self.pstatus.setObjectName("statusBadge")
        self.pmeta = QLabel("")
        self.presolved = QLabel("Resolved request: —")
        self.presolved.setWordWrap(True)
        self.poutput = QLabel("")
        self.poutput.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pretry = QPlainTextEdit()
        self.pretry.setObjectName("queueRetryHistory")
        self.pretry.setReadOnly(True)
        self.pretry.setMaximumHeight(120)
        self.pretry.setPlaceholderText("Retry history: —")
        self.pretry.hide()
        self.ptext = QPlainTextEdit()
        self.ptext.setObjectName("queueDetailsText")
        self.ptext.setReadOnly(True)

        actions = QHBoxLayout()
        self.play_output_button = QPushButton("Play")
        self.play_output_button.setIcon(icon("play"))
        self.open_selected_button = QPushButton("Open")
        self.open_selected_button.setIcon(icon("folder"))
        self.stop_playback_button = QPushButton("Stop")
        self.stop_playback_button.setIcon(icon("stop"))
        self.copy_output_button = QPushButton("Copy")
        self.copy_output_button.setIcon(icon("copy"))
        self.play_output_button.clicked.connect(play_output)
        self.open_selected_button.clicked.connect(open_output)
        self.stop_playback_button.clicked.connect(stop_playback)
        self.copy_output_button.clicked.connect(copy_output)
        for button in (
            self.play_output_button,
            self.open_selected_button,
            self.copy_output_button,
            self.stop_playback_button,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            actions.addWidget(button)

        for widget in (
            self.pname,
            self.pstatus,
            self.pmeta,
            self.presolved,
            self.poutput,
            self.pretry,
            self.ptext,
        ):
            root.addWidget(widget)
        root.addLayout(actions)
