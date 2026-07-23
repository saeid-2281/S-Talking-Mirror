from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QFormLayout, QWidget

from app.gui.widgets import ControlledDoubleSpinBox, ControlledSpinBox


def main() -> None:
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("S Talking spinbox demo")
    layout = QFormLayout(window)

    delay = ControlledDoubleSpinBox()
    delay.setRange(0, 60)
    delay.setDecimals(1)
    delay.setSingleStep(0.1)
    delay.setSuffix(" s")
    delay.setValue(0.5)

    speed = ControlledDoubleSpinBox()
    speed.setRange(0.7, 1.2)
    speed.setDecimals(2)
    speed.setSingleStep(0.05)
    speed.setSuffix("×")
    speed.setValue(1.0)

    retries = ControlledSpinBox()
    retries.setRange(0, 10)
    retries.setSingleStep(1)
    retries.setValue(4)

    layout.addRow("Delay", delay)
    layout.addRow("Speed", speed)
    layout.addRow("Retries", retries)
    window.resize(320, 160)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
