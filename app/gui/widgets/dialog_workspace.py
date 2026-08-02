from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.widgets.professional_components import DialogHeader


class DialogWorkspace(QWidget):
    """Reusable dialog shell with scrollable content and a sticky action bar.

    Dialogs often become taller than the available desktop area after text
    scaling, Windows display scaling, or localization. Keeping the footer
    outside the scroll area guarantees that primary and cancel actions remain
    reachable without relying on resize event filters or dynamic reparenting.
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        icon_name: str = "settings",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dialogWorkspace")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.header = DialogHeader(title, subtitle, icon_name=icon_name, parent=self)
        root.addWidget(self.header)

        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("dialogBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.body = QWidget()
        self.body.setObjectName("dialogBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        self.body_scroll.setWidget(self.body)
        root.addWidget(self.body_scroll, 1)

        self.footer = QFrame(self)
        self.footer.setObjectName("dialogStickyFooter")
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(12, 9, 12, 9)
        self.footer_layout.setSpacing(8)
        root.addWidget(self.footer)

    def add_body_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_body_stretch(self, stretch: int = 1) -> None:
        self.body_layout.addStretch(stretch)

    def add_footer_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.footer_layout.addWidget(widget, stretch)

    def add_footer_stretch(self, stretch: int = 1) -> None:
        self.footer_layout.addStretch(stretch)


class DialogSection(QFrame):
    """Consistent titled card for dialog forms, summaries and tables."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dialogSection")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("dialogSectionTitle")
        root.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("dialogSectionSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        root.addWidget(self.subtitle_label)

        self.content = QWidget()
        self.content.setObjectName("dialogSectionContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 2, 0, 0)
        self.content_layout.setSpacing(8)
        root.addWidget(self.content)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.content_layout.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:  # noqa: ANN001
        self.content_layout.addLayout(layout, stretch)


class DialogStatusCard(QFrame):
    """Compact summary card with semantic state and wrapped supporting text."""

    def __init__(
        self,
        title: str,
        detail: str = "",
        *,
        tone: str = "info",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dialogStatusCard")
        self.setProperty("tone", tone)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("dialogStatusTitle")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("dialogStatusDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)

    def update_status(self, title: str, detail: str, *, tone: str | None = None) -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        if tone is not None:
            self.setProperty("tone", tone)
            self.style().unpolish(self)
            self.style().polish(self)
