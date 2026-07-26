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


def save(window: MainWindow, app: QApplication, output: Path, name: str, width: int, height: int, theme: str, preset: str) -> None:
    window.setGeometry(0, 0, width, height)
    window.apply_theme(theme)
    window.apply_workspace_preset(preset)
    window.show()
    app.processEvents()
    window.grab().save(str(output / f"{name}.png"))


def grab_current(window: MainWindow, app: QApplication, output: Path, name: str, width: int, height: int, theme: str) -> None:
    window.setGeometry(0, 0, width, height)
    window.apply_theme(theme)
    window.show()
    app.processEvents()
    window.grab().save(str(output / f"{name}.png"))


def load_queue(window: MainWindow, runtime: Path) -> None:
    csv_path = Path("input.repaired.csv") if Path("input.repaired.csv").exists() else Path("sample/input.csv")
    window.csv.setText(str(csv_path.resolve()))
    window.out.setText(str((runtime / "Output").resolve()))
    window.load_csv(update_project=False, source="Screenshot")
    if window.table.rowCount():
        window.table.selectRow(0)


def main() -> None:
    output = Path("artifacts/screenshots/v0182/before-after")
    output.mkdir(parents=True, exist_ok=True)
    before = Path("artifacts/screenshots/v0181/before-after/after-dark-1920x1080-wide.png")
    if before.exists():
        shutil.copyfile(before, output / "before-v0181-dark-1920x1080-wide.png")

    runtime = Path(".pytest-tmp/screenshot-v0182")
    shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    QSettings("S Talking", "S Talking").clear()

    empty = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(runtime / "empty"))))
    save(empty, app, output, "empty-project-state-dark-1366x768", 1366, 768, "Dark", "Compact")
    empty.close()

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(runtime / "loaded"))))
    load_queue(window, runtime)
    for theme in ["Dark", "Light"]:
        save(window, app, output, f"{theme.lower()}-1366x768-loaded", 1366, 768, theme, "Compact")
        save(window, app, output, f"{theme.lower()}-1920x1080-loaded", 1920, 1080, theme, "Wide")
        save(window, app, output, f"{theme.lower()}-3840x2160-loaded", 3840, 2160, theme, "Wide")

    window.apply_theme("Dark")
    window.apply_workspace_preset("Standard")
    window.api_profile.addItem("Production ElevenLabs account with long readable profile name · 1,234,567 chars", "long")
    window.api_profile.setCurrentIndex(window.api_profile.count() - 1)
    window.voice.setText("Danish narrator production voice with long descriptive name")
    window.model.addItem("Eleven Multilingual v2 production quality model with long display name", "long-model")
    window.model.setCurrentIndex(window.model.count() - 1)
    save(window, app, output, "provider-panel-full-values", 1366, 768, "Dark", "Standard")

    window.provider.showPopup()
    app.processEvents()
    QApplication.primaryScreen().grabWindow(0).save(str(output / "provider-combo-popup.png"))
    window.provider.hidePopup()

    window.project_menu.popup(window.mapToGlobal(QPoint(28, 42)))
    app.processEvents()
    QApplication.primaryScreen().grabWindow(0).save(str(output / "project-menu.png"))
    window.project_menu.hide()

    window.set_activity_expanded(False)
    grab_current(window, app, output, "activity-collapsed", 1366, 768, "Dark")
    window.set_activity_expanded(True)
    grab_current(window, app, output, "activity-expanded", 1366, 768, "Dark")

    window.right_tabs.setCurrentIndex(0)
    grab_current(window, app, output, "selected-row-populated", 1366, 768, "Dark")
    window.right_tabs.setCurrentIndex(1)
    window.monitor_service.start_run(window.generation_controller.generation_jobs(), provider="mock", output_dir=Path(window.out.text()), settings=window.settings())
    grab_current(window, app, output, "generation-monitor-active", 1366, 768, "Dark")

    summary = output / "visual-change-summary.md"
    summary.write_text(
        "# v0.18.2 Visual Change Summary\n\n"
        "- Removed duplicate central status counters; status values live only in the compact metrics strip.\n"
        "- Metrics are clickable filters with active-state styling.\n"
        "- Provider controls use fixed icon buttons, wider editors, popover-width combo boxes, and collapsible sections.\n"
        "- Toolbar primary actions stay visible while secondary actions move into overflow.\n"
        "- Empty and activity states are compact by default, with loaded-queue screenshots using the 4,212-row repaired CSV.\n",
        encoding="utf-8",
    )
    window.close()
    print(output.resolve())


if __name__ == "__main__":
    main()
