from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook  # noqa: E402
from PySide6.QtCore import QItemSelectionModel, QPoint, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.bootstrap import create_application_context  # noqa: E402
from app.config.runtime import RuntimeConfig  # noqa: E402
from app.container import create_service_container  # noqa: E402
from app.gui.dialogs.preflight_dialog import PreflightDialog  # noqa: E402
from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog  # noqa: E402
from app.gui.dialogs.pronunciation_dictionary_dialog import PronunciationDictionaryDialog  # noqa: E402
from app.gui.main import MainWindow  # noqa: E402
from app.models import AppSettings  # noqa: E402
from app.models.preflight_state import PreflightIssue, PreflightState  # noqa: E402
from app.models.pronunciation_dictionary import PronunciationRule  # noqa: E402


def save_widget(widget, app: QApplication, output: Path, name: str, width: int | None = None, height: int | None = None) -> None:
    if width and height:
        widget.setGeometry(0, 0, width, height)
    widget.show()
    app.processEvents()
    widget.grab().save(str(output / f"{name}.png"))


def create_sample_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet A"
    sheet.append(["text", "filename"])
    sheet.append(["Hej fra Excel", "excel-a.mp3"])
    second = workbook.create_sheet("Sheet B")
    second.append(["filename", "text"])
    second.append(["excel-b.mp3", "Tak fra Excel"])
    workbook.save(path)


def load_sources(window: MainWindow, runtime: Path) -> None:
    csv_path = Path("input.repaired.csv").resolve()
    xlsx_path = runtime / "sample-source.xlsx"
    create_sample_xlsx(xlsx_path)
    project = window.project_controller.new_project("v0183 screenshots", csv_path, runtime / "Output", window.settings())
    window.apply_project_state(project)
    sources = window.context.source_import_service.create_sources([csv_path, xlsx_path], project_id=project.project_id)
    result = window.context.source_import_service.import_sources(sources)
    window.project_sources = [item.source for item in result.sources]
    jobs = window.context.source_import_service.assign_merged_row_numbers(result.jobs)
    window.generation_controller.set_jobs(jobs, project_id=project.project_id, output_dir=runtime / "Output", settings=window.settings())
    window.context.source_repository.upsert_sources(project.project_id, window.project_sources)
    window.render_project_sources()
    window.render_queue()
    window.refresh_monitor_queue()
    window.dashboard()
    if window.table.rowCount():
        window.table.selectRow(0)


def quota_warning_state() -> PreflightState:
    issue = PreflightIssue(
        "warning",
        None,
        "",
        "ElevenLabs quota shortfall. Required: 345,935 characters. Available: 10,000 characters. Shortfall: 335,935 characters.",
        "Continue anyway, select a smaller scope, auto-select jobs that fit quota, choose another account, or enable account failover.",
        code="insufficient_quota",
    )
    return PreflightState(
        total_jobs=4212,
        valid_jobs=4212,
        blocking_errors=0,
        warnings=1,
        estimated_characters=345_935,
        estimated_files=4212,
        estimated_duration_seconds=12636,
        estimated_provider_requests=4212,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        issues=[issue],
    )


def main() -> None:
    output = Path("artifacts/screenshots/v0183")
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)
    runtime = Path(".pytest-tmp/screenshot-v0183")
    shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    QSettings("S Talking", "S Talking").clear()

    container = create_service_container(RuntimeConfig.from_root(runtime))
    window = MainWindow(create_application_context(container))
    load_sources(window, runtime)

    for theme in ["Dark", "Light"]:
        window.apply_theme(theme)
        window.apply_workspace_preset("Compact")
        save_widget(window, app, output, f"{theme.lower()}-main-workspace-4212-jobs", 1366, 768)

    window.left_tabs.setCurrentIndex(window.left_tabs.indexOf(window.sources_table.parentWidget()))
    save_widget(window, app, output, "sources-tab-populated", 1366, 768)

    window.queue_header_clicked(1)
    save_widget(window, app, output, "queue-sorted-filename-ascending", 1366, 768)
    window.queue_header_clicked(1)
    save_widget(window, app, output, "queue-sorted-filename-descending", 1366, 768)

    for row in range(min(100, window.table.rowCount())):
        window.table.selectionModel().select(
            window.table.model().index(row, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )
    window.use_selection_as_scope()
    save_widget(window, app, output, "selected-100-row-scope-summary", 1366, 768)

    preflight = PreflightDialog(quota_warning_state(), export_report=lambda: output, open_output_folder=lambda: None, apply_fixes=lambda: None)
    save_widget(preflight, app, output, "quota-shortfall-warning-continue", 980, 560)
    preflight.close()

    container.api_profile_service.create_profile("Safe test primary", api_key="sk_safe_primary", active=True)
    container.api_profile_service.create_profile("Safe test backup", api_key="sk_safe_backup")
    accounts = ProviderAccountsDialog(container.api_profile_service, container.voice_service, lambda: AppSettings(provider="elevenlabs"))
    save_widget(accounts, app, output, "provider-accounts-two-safe-profiles", 1040, 640)
    accounts.close()

    window.set_provider_status("Connected · Free tier · 21 voices")
    save_widget(window, app, output, "connection-success-result", 1366, 768)
    window.set_provider_status("Invalid API key")
    save_widget(window, app, output, "connection-error-result", 1366, 768)

    pronunciation = PronunciationDictionaryDialog(container.pronunciation_dictionary_service, lambda: AppSettings(provider="elevenlabs", language_code="da"))
    save_widget(pronunciation, app, output, "pronunciation-dictionary-empty-onboarding", 1080, 660)
    dictionary = container.pronunciation_dictionary_service.create("Local tutorial example", language_code="da")
    container.pronunciation_dictionary_service.add_rule(
        dictionary.dictionary_id,
        PronunciationRule(source="Example", replacement="user-entered pronunciation", rule_type="alias", language_code="da"),
    )
    pronunciation.refresh()
    save_widget(pronunciation, app, output, "dictionary-rule-editor", 1080, 660)
    pronunciation.close()

    window.project_menu.popup(window.mapToGlobal(QPoint(28, 42)))
    app.processEvents()
    QApplication.primaryScreen().grabWindow(0).save(str(output / "project-menu-hover.png"))
    window.project_menu.hide()

    save_widget(window, app, output, "toolbar-hover-pressed-state", 1366, 768)
    window.close()
    print(output.resolve())


if __name__ == "__main__":
    main()
