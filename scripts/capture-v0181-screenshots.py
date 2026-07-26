from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.bootstrap import create_application_context  # noqa: E402
from app.config.runtime import RuntimeConfig  # noqa: E402
from app.container import create_service_container  # noqa: E402
from app.gui.main import MainWindow  # noqa: E402
from app.gui.voice_browser import VoiceBrowserDialog  # noqa: E402


def capture_window(window: MainWindow, app: QApplication, output: Path, name: str, width: int, height: int, theme: str, preset: str) -> None:
    window.resize(width, height)
    window.apply_theme(theme)
    window.apply_workspace_preset(preset)
    window.show()
    app.processEvents()
    window.grab().save(str(output / f"{name}.png"))


def main() -> None:
    output = Path("artifacts/screenshots/v0181/before-after")
    output.mkdir(parents=True, exist_ok=True)
    before = Path("artifacts/screenshots/v018/dark-1920x1080.png")
    if before.exists():
        shutil.copyfile(before, output / "before-v018-dark-1920x1080.png")

    temp_runtime = Path(".pytest-tmp/screenshot-v0181")
    shutil.rmtree(temp_runtime, ignore_errors=True)
    temp_runtime.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    QSettings("S Talking", "S Talking").clear()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(temp_runtime))))
    csv_path = Path("input.repaired.csv") if Path("input.repaired.csv").exists() else Path("sample/input.csv")
    window.csv.setText(str(csv_path.resolve()))
    window.out.setText(str((temp_runtime / "Output").resolve()))
    window.load_csv(update_project=False, source="Screenshot")

    shots = [
        ("after-dark-1366x768-compact", 1366, 768, "Dark", "Compact"),
        ("after-dark-1680x945-standard", 1680, 945, "Dark", "Standard"),
        ("after-dark-1920x1080-wide", 1920, 1080, "Dark", "Wide"),
        ("after-light-1920x1080-standard", 1920, 1080, "Light", "Standard"),
        ("after-dark-3840x2160-wide", 3840, 2160, "Dark", "Wide"),
    ]
    for args in shots:
        capture_window(window, app, output, *args)

    window.apply_theme("Light")
    window.apply_workspace_preset("Standard")
    window.resize(1680, 945)
    window.show()
    app.processEvents()
    window.project_menu.popup(window.mapToGlobal(QPoint(32, 42)))
    app.processEvents()
    window.grab().save(str(output / "after-project-menu-1680x945.png"))
    window.project_menu.hide()

    try:
        error_file = output / "voice-browser-capture-error.txt"
        if error_file.exists():
            error_file.unlink()
        dialog = VoiceBrowserDialog(
            service=window.context.voice_service,
            settings_provider=window.settings,
            desktop_service=window.context.desktop_service,
            audio_player_service=window.audio_player_service,
            parent=window,
        )
        dialog.resize(1000, 680)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / "after-voice-browser-1000x680.png"))
        dialog.close()
    except Exception as exc:
        (output / "voice-browser-capture-error.txt").write_text(str(exc), encoding="utf-8")

    window.close()
    print(output.resolve())


if __name__ == "__main__":
    main()
