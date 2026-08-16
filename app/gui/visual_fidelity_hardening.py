from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QFrame,
    QLabel,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from app.gui.icons import action_icon


class VisualFidelityHardener(QObject):
    """Presentation-only repairs for the post-A11 Soft Professional review."""

    TOOLBAR_ICON_SIZE = 20
    METRIC_RADIUS = 12
    MONITOR_MIN_WIDTH = 320
    MONITOR_TARGET_WIDTH = 340
    PROVIDER_ACCOUNTS_MIN_WIDTH = 1160
    PROVIDER_ACCOUNTS_MIN_HEIGHT = 720
    PROVIDER_DETAILS_MIN_WIDTH = 420

    TOOLBAR_ICON_MAP = {
        "New Project": "project.new",
        "Open Project": "project.open",
        "Save": "project.save",
        "Add source files": "project.add_sources",
        "Start Generation": "generation.start",
        "Pause/Resume": "generation.pause",
        "Stop Generation": "generation.stop",
        "Run Preflight": "generation.preflight",
        "Voice Browser": "provider.browse_voices",
    }

    METRIC_STYLE = """
QFrame#metricPill {
    border-radius: 12px;
}
QFrame#metricPill:hover,
QFrame#metricPill[active="true"],
QFrame#metricPill[active="false"] {
    border-radius: 12px;
}
""".strip()

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.owner = owner
        self._installed = False
        self._refresh_pending = False

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

        right_tabs = getattr(self.owner, "right_tabs", None)
        if isinstance(right_tabs, QTabWidget):
            right_tabs.currentChanged.connect(self._right_tab_changed)

        self.refresh_main_window()
        QTimer.singleShot(0, self.refresh_main_window)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.Show and isinstance(watched, QDialog):
            if self._is_provider_accounts_dialog(watched):
                QTimer.singleShot(
                    0,
                    lambda dialog=watched: self._polish_dialog_if_alive(dialog),
                )
        elif watched is self.owner and event_type in {
            QEvent.Type.Show,
            QEvent.Type.Resize,
        }:
            self._schedule_refresh()
        return False

    @staticmethod
    def _is_provider_accounts_dialog(dialog: QDialog) -> bool:
        try:
            object_name = dialog.objectName().casefold()
            title = dialog.windowTitle().casefold()
        except RuntimeError:
            return False
        return object_name == "provideraccountsdialog" or "provider accounts" in title

    def _polish_dialog_if_alive(self, dialog: QDialog) -> None:
        try:
            self.polish_dialog(dialog)
        except RuntimeError as exc:
            # A deferred Qt callback may outlive a WA_DeleteOnClose dialog.
            # Ignore only the canonical deleted-wrapper condition; other
            # runtime failures remain visible to tests and operators.
            message = str(exc).casefold()
            if "already deleted" not in message and "internal c++ object" not in message:
                raise

    def _schedule_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._finish_scheduled_refresh)

    def _finish_scheduled_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh_main_window()

    def refresh_main_window(self) -> None:
        self._harden_toolbar()
        self._harden_metrics()
        self.refresh_monitor()
        self.refresh_provider_overview()

    def _harden_toolbar(self) -> None:
        toolbar = getattr(self.owner, "main_toolbar", None)
        if not isinstance(toolbar, QToolBar):
            return

        toolbar.setIconSize(QSize(self.TOOLBAR_ICON_SIZE, self.TOOLBAR_ICON_SIZE))
        toolbar.setProperty("visualFidelityIcons", "canonical")

        actions = getattr(self.owner, "actions_by_name", {})
        for action_name, icon_name in self.TOOLBAR_ICON_MAP.items():
            action = actions.get(action_name)
            if action is None:
                continue
            # Always replace legacy/mixed toolbar icons. The toolbar therefore
            # has one canonical SVG/icon path and one pixel size.
            action.setIcon(action_icon(icon_name, size=self.TOOLBAR_ICON_SIZE))
            action.setProperty("visualFidelityIcon", icon_name)

        overflow = getattr(self.owner, "toolbar_overflow_button", None)
        if isinstance(overflow, QToolButton):
            overflow.setIcon(action_icon("general.more", size=self.TOOLBAR_ICON_SIZE))

        for button in toolbar.findChildren(QToolButton):
            button.setIconSize(QSize(self.TOOLBAR_ICON_SIZE, self.TOOLBAR_ICON_SIZE))
            button.setMinimumHeight(32)
            button.setMaximumHeight(34)
            policy = button.sizePolicy()
            policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
            button.setSizePolicy(policy)
            button.setProperty("visualFidelityAlignment", "toolbar")

    def _harden_metrics(self) -> None:
        cards = getattr(self.owner, "cards", {})
        for card in cards.values():
            if not isinstance(card, QFrame):
                continue
            card.setProperty("visualFidelityRadius", self.METRIC_RADIUS)
            if card.styleSheet() != self.METRIC_STYLE:
                card.setStyleSheet(self.METRIC_STYLE)
            card.setMinimumHeight(max(34, card.minimumHeight()))
            card.setMaximumHeight(min(42, card.maximumHeight()))
            card.update()

    def _right_tab_changed(self, _index: int) -> None:
        QTimer.singleShot(0, self.refresh_monitor)

    def _monitor_tab_active(self) -> bool:
        tabs = getattr(self.owner, "right_tabs", None)
        if not isinstance(tabs, QTabWidget):
            return False
        index = tabs.currentIndex()
        return index >= 0 and tabs.tabText(index).strip().casefold() == "generation monitor"

    def refresh_monitor(self) -> None:
        dock = getattr(self.owner, "monitor_dock", None)
        if dock is None:
            dock = getattr(self.owner, "right_dock", None)
        if dock is None:
            return

        # Preserve the historical 290px minimum-width API contract. A11.1
        # improves usability by resizing the *actual* active dock width instead.
        dock.setMinimumWidth(290)
        dock.setMaximumWidth(self.MONITOR_TARGET_WIDTH)
        dock.setProperty("visualFidelityMonitor", True)

        scroll = getattr(self.owner, "monitor_scroll", None)
        if scroll is not None:
            scroll.setMinimumWidth(0)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            panel = scroll.widget()
            if panel is not None:
                panel.setMinimumWidth(0)
                panel.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Preferred,
                )
                for label in panel.findChildren(QLabel):
                    label.setMinimumWidth(0)
                    if len(label.text().strip()) > 28:
                        label.setWordWrap(True)
                for button in panel.findChildren(QAbstractButton):
                    button.setMinimumWidth(0)
                    policy = button.sizePolicy()
                    policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
                    button.setSizePolicy(policy)

        for tab_widget in (
            getattr(self.owner, "right_tabs", None),
            getattr(self.owner, "monitor_sections", None),
        ):
            if isinstance(tab_widget, QTabWidget):
                tab_widget.setMinimumWidth(0)
                tab_widget.tabBar().setUsesScrollButtons(True)
                tab_widget.tabBar().setElideMode(Qt.TextElideMode.ElideRight)

        if self._monitor_tab_active() and dock.isVisible():
            try:
                # B2 can repolish the dock while attaching semantic surface
                # properties. Some Qt/Windows layouts then remember the
                # historical 290px minimum as the actual dock width and ignore
                # a single resizeDocks() request. Temporarily clamping the dock
                # to the requested width gives QMainWindow's dock layout an
                # unambiguous geometry request; the public minimum-width
                # contract is restored immediately afterwards.
                historical_minimum = 290
                target_width = self.MONITOR_TARGET_WIDTH

                dock.setMinimumWidth(target_width)
                dock.setMaximumWidth(target_width)
                dock.updateGeometry()
                layout = self.owner.layout()
                if layout is not None:
                    layout.activate()

                self.owner.resizeDocks(
                    [dock],
                    [target_width],
                    Qt.Orientation.Horizontal,
                )
                dock.resize(target_width, dock.height())

                dock.setMinimumWidth(historical_minimum)
                dock.setMaximumWidth(target_width)
                dock.updateGeometry()
                self.owner.resizeDocks(
                    [dock],
                    [target_width],
                    Qt.Orientation.Horizontal,
                )
                dock.resize(target_width, dock.height())
                if layout is not None:
                    layout.activate()

                dock.setProperty("visualFidelityRequestedWidth", target_width)
            except (AttributeError, RuntimeError):
                # The hardener is presentation-only. A deleted/closing Qt
                # wrapper must not affect application shutdown or workflow
                # authority.
                pass

    def refresh_provider_overview(self) -> None:
        overview = getattr(self.owner, "provider_overview", None)
        if not isinstance(overview, QWidget):
            return

        overview.setProperty("visualFidelityProviderOverview", True)
        overview.setMinimumWidth(0)
        overview.setMaximumWidth(16777215)
        overview.setMaximumHeight(16777215)
        overview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        layout = overview.layout()
        if layout is not None:
            layout.setSpacing(max(6, layout.spacing()))

        for widget in overview.findChildren(QWidget):
            widget.setMinimumWidth(0)

        for label in overview.findChildren(QLabel):
            label.setMinimumWidth(0)
            policy = label.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            if len(label.text().strip()) > 22:
                policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
                label.setMaximumHeight(16777215)
                label.setWordWrap(True)
                if not label.toolTip():
                    label.setToolTip(label.text())
            label.setSizePolicy(policy)

        for button in overview.findChildren(QAbstractButton):
            button.setMinimumWidth(0)
            policy = button.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            button.setSizePolicy(policy)
            text = button.text().strip()
            if len(text) > 20:
                self._elide_button_text(button, 136)

    @staticmethod
    def _elide_button_text(button: QAbstractButton, pixel_width: int) -> None:
        current = button.text()
        previous_elided = str(button.property("visualFidelityElidedText") or "")
        full_text = str(button.property("visualFidelityFullText") or "")
        if not full_text or current != previous_elided:
            full_text = current
            button.setProperty("visualFidelityFullText", full_text)
        if not button.toolTip():
            button.setToolTip(full_text)
        elided = button.fontMetrics().elidedText(
            full_text,
            Qt.TextElideMode.ElideRight,
            pixel_width,
        )
        button.setProperty("visualFidelityElidedText", elided)
        if current != elided:
            button.setText(elided)

    def polish_dialog(self, dialog: QDialog) -> None:
        if not self._is_provider_accounts_dialog(dialog):
            return
        self._harden_provider_accounts(dialog)

    def _harden_provider_accounts(self, dialog: QDialog) -> None:
        dialog.setProperty("visualFidelityProviderAccounts", True)
        dialog.setMinimumSize(
            self.PROVIDER_ACCOUNTS_MIN_WIDTH,
            self.PROVIDER_ACCOUNTS_MIN_HEIGHT,
        )

        if (
            dialog.width() < self.PROVIDER_ACCOUNTS_MIN_WIDTH
            or dialog.height() < self.PROVIDER_ACCOUNTS_MIN_HEIGHT
        ):
            dialog.resize(
                max(dialog.width(), self.PROVIDER_ACCOUNTS_MIN_WIDTH),
                max(dialog.height(), self.PROVIDER_ACCOUNTS_MIN_HEIGHT),
            )

        splitter = dialog.findChild(QSplitter, "providerAccountsSplitter")
        details = dialog.findChild(QWidget, "providerAccountDetails")

        if details is not None:
            details.setMinimumWidth(self.PROVIDER_DETAILS_MIN_WIDTH)
            details.setMaximumWidth(520)
            details.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Expanding,
            )
            details_layout = details.layout()
            if details_layout is not None:
                details_layout.setContentsMargins(14, 12, 14, 14)
                details_layout.setSpacing(max(8, details_layout.spacing()))

            for label in details.findChildren(QLabel):
                label.setMinimumWidth(0)
                policy = label.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
                label.setSizePolicy(policy)
                if len(label.text().strip()) > 20:
                    label.setMaximumHeight(16777215)
                    label.setWordWrap(True)

            for button in details.findChildren(QAbstractButton):
                button.setMinimumWidth(78)
                button.setMinimumHeight(max(34, button.minimumHeight()))
                policy = button.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.MinimumExpanding)
                policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
                button.setSizePolicy(policy)

        if splitter is not None and details is not None:
            splitter.setChildrenCollapsible(False)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 0)
            total = max(dialog.width() - 48, 1040)
            details_width = min(460, max(self.PROVIDER_DETAILS_MIN_WIDTH, total // 3))
            splitter.setSizes([max(620, total - details_width), details_width])
            splitter.setProperty("visualFidelityDetailsWidth", details_width)
