from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPolygon, QWheelEvent
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox, QStyle, QStyleOptionSpinBox


class SpinBoxUxMixin:
    """Reliable spinbox buttons and cursor behavior under Qt stylesheets."""

    repeat_delay_ms = 400
    repeat_interval_ms = 80

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self.lineEdit().setMouseTracking(True)
        self.lineEdit().installEventFilter(self)
        self._pressed_step = 0
        self._hover_subcontrol = QStyle.SC_None
        self._pressed_subcontrol = QStyle.SC_None
        self._repeat_delay = QTimer(self)
        self._repeat_delay.setSingleShot(True)
        self._repeat_delay.timeout.connect(self._start_repeat)
        self._repeat_timer = QTimer(self)
        self._repeat_timer.timeout.connect(self._repeat_step)

    def style_option(self) -> QStyleOptionSpinBox:
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        return option

    def subcontrol_rect(self, subcontrol: QStyle.SubControl) -> QRect:
        return self.style().subControlRect(QStyle.CC_SpinBox, self.style_option(), subcontrol, self)

    def subcontrol_at(self, position: QPoint) -> QStyle.SubControl:
        for subcontrol in (QStyle.SC_SpinBoxUp, QStyle.SC_SpinBoxDown, QStyle.SC_SpinBoxEditField):
            if self.subcontrol_rect(subcontrol).contains(position):
                return subcontrol
        return QStyle.SC_None

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._update_cursor(self._event_position(event))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        self.lineEdit().unsetCursor()
        self._hover_subcontrol = QStyle.SC_None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._maybe_press_button(event, self._event_position(event)):
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._stop_repeat()
        self._pressed_subcontrol = QStyle.SC_None
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._draw_arrow(painter, QStyle.SC_SpinBoxUp)
        self._draw_arrow(painter, QStyle.SC_SpinBoxDown)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.lineEdit():
            event_type = event.type()
            if event_type == QEvent.MouseMove:
                self._update_cursor(self._line_edit_event_position(event))
            elif event_type == QEvent.MouseButtonPress and self._maybe_press_button(
                event,
                self._line_edit_event_position(event),
            ):
                return True
            elif event_type == QEvent.MouseButtonRelease:
                self._stop_repeat()
        return super().eventFilter(watched, event)

    def _maybe_press_button(self, event: QMouseEvent, position: QPoint) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        subcontrol = self.subcontrol_at(position)
        if subcontrol == QStyle.SC_SpinBoxUp:
            self._pressed_subcontrol = subcontrol
            self._press_step(1)
            event.accept()
            self.update()
            return True
        if subcontrol == QStyle.SC_SpinBoxDown:
            self._pressed_subcontrol = subcontrol
            self._press_step(-1)
            event.accept()
            self.update()
            return True
        return False

    def _press_step(self, step: int) -> None:
        self.setFocus(Qt.MouseFocusReason)
        self._pressed_step = step
        self.stepBy(step)
        self._repeat_delay.start(self.repeat_delay_ms)

    def _start_repeat(self) -> None:
        if self._pressed_step:
            self._repeat_timer.start(self.repeat_interval_ms)

    def _repeat_step(self) -> None:
        if self._pressed_step:
            self.stepBy(self._pressed_step)

    def _stop_repeat(self) -> None:
        self._pressed_step = 0
        self._repeat_delay.stop()
        self._repeat_timer.stop()

    def _update_cursor(self, position: QPoint) -> None:
        subcontrol = self.subcontrol_at(position)
        if subcontrol != self._hover_subcontrol:
            self._hover_subcontrol = subcontrol
            self.update()
        cursor = QCursor(Qt.IBeamCursor if subcontrol == QStyle.SC_SpinBoxEditField else Qt.ArrowCursor)
        self.setCursor(cursor)
        self.lineEdit().setCursor(cursor)

    def _draw_arrow(self, painter: QPainter, subcontrol: QStyle.SubControl) -> None:
        rect = self.subcontrol_rect(subcontrol)
        if rect.isEmpty():
            return
        center = rect.center()
        half_width = max(4, min(6, rect.width() // 4))
        half_height = max(3, min(5, rect.height() // 3))
        if subcontrol == QStyle.SC_SpinBoxUp:
            points = [
                QPoint(center.x() - half_width, center.y() + half_height // 2),
                QPoint(center.x() + half_width, center.y() + half_height // 2),
                QPoint(center.x(), center.y() - half_height),
            ]
        else:
            points = [
                QPoint(center.x() - half_width, center.y() - half_height // 2),
                QPoint(center.x() + half_width, center.y() - half_height // 2),
                QPoint(center.x(), center.y() + half_height),
            ]
        if not self.isEnabled():
            color = QColor("#64748B")
        elif subcontrol == self._pressed_subcontrol:
            color = QColor("#FFFFFF")
        elif subcontrol == self._hover_subcontrol:
            color = QColor("#F8FAFC")
        else:
            color = QColor("#CBD5E1")
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygon(points))

    def _line_edit_event_position(self, event: QEvent) -> QPoint:
        return self.lineEdit().mapTo(self, self._event_position(event))

    def _event_position(self, event: QEvent) -> QPoint:
        position = getattr(event, "position", None)
        if callable(position):
            return position().toPoint()
        return event.pos()


class ControlledSpinBox(SpinBoxUxMixin, QSpinBox):
    pass


class ControlledDoubleSpinBox(SpinBoxUxMixin, QDoubleSpinBox):
    pass
