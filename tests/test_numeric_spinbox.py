from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QStyle

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.widgets import ControlledDoubleSpinBox, ControlledSpinBox


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def main_window(qt_app, tmp_path: Path):
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.resize(1420, 860)
    window.show()
    qt_app.processEvents()
    yield window
    window.close()
    qt_app.processEvents()


def test_delay_up_subcontrol_click_increments_by_point_one(main_window) -> None:
    before = main_window.delay.value()

    QTest.mouseClick(main_window.delay, Qt.LeftButton, pos=spin_rect(main_window.delay, QStyle.SC_SpinBoxUp).center())

    assert main_window.delay.value() == pytest.approx(before + 0.1)


def test_delay_down_subcontrol_click_decrements_by_point_one(main_window) -> None:
    main_window.delay.setValue(0.5)

    QTest.mouseClick(main_window.delay, Qt.LeftButton, pos=spin_rect(main_window.delay, QStyle.SC_SpinBoxDown).center())

    assert main_window.delay.value() == pytest.approx(0.4)


def test_speed_up_subcontrol_click_increments_by_point_zero_five(main_window) -> None:
    before = main_window.speed.value()

    QTest.mouseClick(main_window.speed, Qt.LeftButton, pos=spin_rect(main_window.speed, QStyle.SC_SpinBoxUp).center())

    assert main_window.speed.value() == pytest.approx(before + 0.05)


def test_retries_up_subcontrol_click_increments_by_one(main_window) -> None:
    before = main_window.retries.value()

    QTest.mouseClick(main_window.retries, Qt.LeftButton, pos=spin_rect(main_window.retries, QStyle.SC_SpinBoxUp).center())

    assert main_window.retries.value() == before + 1


def test_spinbox_subcontrol_rectangles_are_real_and_separate(main_window) -> None:
    for spinbox in numeric_controls(main_window):
        edit = spin_rect(spinbox, QStyle.SC_SpinBoxEditField)
        up = spin_rect(spinbox, QStyle.SC_SpinBoxUp)
        down = spin_rect(spinbox, QStyle.SC_SpinBoxDown)

        assert up.width() > 0
        assert up.height() > 0
        assert down.width() > 0
        assert down.height() > 0
        assert edit != up
        assert edit != down
        assert not edit.contains(up)
        assert not edit.contains(down)


def test_spinbox_cursor_uses_actual_subcontrols(qt_app, main_window) -> None:
    QTest.mouseMove(main_window.delay, QPoint(0, 0))
    QTest.mouseMove(main_window.delay, spin_rect(main_window.delay, QStyle.SC_SpinBoxEditField).center())
    qt_app.processEvents()
    assert main_window.delay.cursor().shape() == Qt.IBeamCursor

    QTest.mouseMove(main_window.delay, spin_rect(main_window.delay, QStyle.SC_SpinBoxUp).center())
    qt_app.processEvents()
    assert main_window.delay.cursor().shape() == Qt.ArrowCursor

    QTest.mouseMove(main_window.delay, spin_rect(main_window.delay, QStyle.SC_SpinBoxDown).center())
    qt_app.processEvents()
    assert main_window.delay.cursor().shape() == Qt.ArrowCursor


def test_unfocused_spinbox_ignores_wheel_changes(qt_app, main_window) -> None:
    main_window.provider.setFocus()
    main_window.speed.clearFocus()
    qt_app.processEvents()
    before = main_window.speed.value()
    wheel = QWheelEvent(
        QPointF(1, 1),
        QPointF(1, 1),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )

    qt_app.sendEvent(main_window.speed, wheel)

    assert main_window.speed.value() == pytest.approx(before)


def test_focused_spinbox_accepts_keyboard_up_down(main_window) -> None:
    main_window.delay.setFocus()
    before = main_window.delay.value()

    QTest.keyClick(main_window.delay, Qt.Key_Up)
    assert main_window.delay.value() == pytest.approx(before + 0.1)

    QTest.keyClick(main_window.delay, Qt.Key_Down)
    assert main_window.delay.value() == pytest.approx(before)


def test_all_main_window_numeric_spinboxes_use_fixed_controls(main_window) -> None:
    assert numeric_controls(main_window)
    for spinbox in numeric_controls(main_window):
        assert isinstance(spinbox, ControlledSpinBox | ControlledDoubleSpinBox)


def test_spinbox_arrow_regions_render_visible_pixels(main_window) -> None:
    for spinbox in [main_window.delay, main_window.speed, main_window.retries]:
        image = spinbox.grab().toImage()
        for subcontrol in [QStyle.SC_SpinBoxUp, QStyle.SC_SpinBoxDown]:
            center = spin_rect(spinbox, subcontrol).center()
            color = image.pixelColor(center)
            assert color.name().lower() != "#1f2937"


def numeric_controls(window) -> list[QAbstractSpinBox]:
    return window.findChildren(QAbstractSpinBox)


def spin_rect(spinbox: ControlledSpinBox | ControlledDoubleSpinBox, subcontrol: QStyle.SubControl):
    return spinbox.subcontrol_rect(subcontrol)
