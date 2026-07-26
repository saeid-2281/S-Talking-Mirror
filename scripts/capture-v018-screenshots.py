from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.bootstrap import create_application_context  # noqa: E402
from app.config.runtime import RuntimeConfig  # noqa: E402
from app.container import create_service_container  # noqa: E402
from app.gui.main import MainWindow  # noqa: E402


def main() -> None:
    output = Path("artifacts/screenshots/v018")
    output.mkdir(parents=True, exist_ok=True)
    temp_runtime = Path(".pytest-tmp/screenshot-v018")
    shutil.rmtree(temp_runtime, ignore_errors=True)
    temp_runtime.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    QSettings("S Talking", "S Talking").clear()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(temp_runtime))))
    shots = [
        ("dark-1366x768", 1366, 768, "Dark", "Compact"),
        ("dark-1920x1080", 1920, 1080, "Dark", "Standard"),
        ("dark-2560x1440", 2560, 1440, "Dark", "Wide"),
        ("dark-3840x2160", 3840, 2160, "Dark", "Wide"),
        ("light-1920x1080", 1920, 1080, "Light", "Standard"),
    ]
    for name, width, height, theme, preset in shots:
        window.resize(width, height)
        window.apply_theme(theme)
        window.apply_workspace_preset(preset)
        window.show()
        app.processEvents()
        window.grab().save(str(output / f"{name}.png"))
    window.close()
    print(output.resolve())


if __name__ == "__main__":
    main()
