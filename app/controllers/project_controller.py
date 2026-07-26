from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.domain import AppSettings
from app.models.persistence import ProjectRecord
from app.models.project_state import PathValidation, ProjectState
from app.models.ui_state import GenerationContext
from app.services.project_manager import ProjectManager


class ProjectController:
    """Coordinates project actions between the GUI and ProjectManager."""

    def __init__(self, project_manager: ProjectManager, runtime: RuntimeConfig) -> None:
        self.project_manager = project_manager
        self.runtime = runtime
        self.last_project_dir = runtime.app_root
        self.last_csv_dir = runtime.app_root
        self.last_output_dir = runtime.default_output_dir

    @property
    def current_project(self) -> ProjectState | None:
        return self.project_manager.current_project

    @property
    def project_name(self) -> str:
        return self.current_project.name if self.current_project else "Untitled project"

    @property
    def default_output_path(self) -> Path:
        return self.runtime.default_output_dir

    @property
    def current_project_key(self) -> str:
        return self.generation_context("").project_key

    def new_project(
        self,
        name: str,
        csv_path: Path | None,
        output_path: Path | None,
        settings: AppSettings,
    ) -> ProjectState:
        if csv_path:
            self.last_csv_dir = Path(csv_path).parent
        if output_path:
            self.last_output_dir = Path(output_path)
        return self.project_manager.new_project(
            name,
            csv_path,
            output_path,
            settings.provider,
            settings,
        )

    def open_project(self, path: Path) -> ProjectState:
        self.last_project_dir = path.parent
        state = self.project_manager.open_project(path)
        if state.csv_path:
            self.last_csv_dir = state.csv_path.parent
        if state.output_path:
            self.last_output_dir = state.output_path
        return state

    def save_project(self, fallback_settings: AppSettings, csv_path: str, output_path: str) -> ProjectState | None:
        if self.current_project is None:
            self.project_manager.new_project(
                "Untitled project",
                csv_path,
                output_path,
                fallback_settings.provider,
                fallback_settings,
            )
        if self.current_project and self.current_project.project_file is None:
            return None
        return self.project_manager.save_project()

    def save_project_as(
        self,
        path: Path,
        fallback_name: str,
        fallback_settings: AppSettings,
        csv_path: str,
        output_path: str,
    ) -> ProjectState:
        if self.current_project is None:
            self.project_manager.new_project(
                fallback_name,
                csv_path,
                output_path,
                fallback_settings.provider,
                fallback_settings,
            )
        self.last_project_dir = path.parent
        return self.project_manager.save_project_as(path)

    def close_project(self) -> None:
        self.project_manager.close_project()

    def update_csv_path(self, path: Path | None) -> None:
        if path:
            self.last_csv_dir = path.parent
        self.project_manager.update_csv_path(path)

    def update_output_path(self, path: Path | None) -> None:
        if path:
            self.last_output_dir = path
        self.project_manager.update_output_path(path)

    def update_provider(self, provider: str) -> None:
        self.project_manager.update_provider(provider)

    def update_settings(self, settings: AppSettings) -> None:
        self.project_manager.update_settings(settings)

    def list_recent_projects(self, limit: int = 10) -> list[ProjectRecord]:
        return self.project_manager.list_recent_projects(limit)

    def remove_recent_project(self, project_id: int) -> None:
        self.project_manager.remove_recent_project(project_id)

    def validate_current_paths(self) -> PathValidation:
        return self.project_manager.validate_current_paths()

    def autosave_if_needed(self, generation_active: bool) -> bool:
        return self.project_manager.autosave_if_needed(generation_active=generation_active)

    def generation_context(self, output_path: str | Path) -> GenerationContext:
        project = self.current_project
        if project is not None:
            return GenerationContext(
                project_name=project.name,
                project_key=project.project_key,
                output_path=project.output_path or self._output_path(output_path),
            )
        fallback_output = self._output_path(output_path)
        fallback_source = f"{fallback_output.resolve()}|Untitled project"
        return GenerationContext(
            project_name="Untitled project",
            project_key=f"adhoc:{hashlib.sha256(fallback_source.encode()).hexdigest()[:24]}",
            output_path=fallback_output,
        )

    def _output_path(self, output_path: str | Path) -> Path:
        if str(output_path):
            return Path(output_path)
        return self.runtime.default_output_dir

    def suggested_save_as_path(self) -> Path:
        project = self.current_project
        if project and project.project_file:
            return project.project_file
        name = self.project_name
        filename = sanitize_project_filename(name)
        return self.last_project_dir / filename


WINDOWS_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_project_filename(project_name: str) -> str:
    """Sanitize only Windows-invalid filename characters."""
    cleaned = WINDOWS_INVALID_FILENAME_CHARS.sub("_", project_name).strip()
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        cleaned = "Untitled project"
    if not cleaned.lower().endswith(".stproj"):
        cleaned = f"{cleaned}.stproj"
    return cleaned
