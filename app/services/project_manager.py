from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.database.connection import Database
from app.database.migrations import utc_now
from app.database.schema import DEFAULT_DATABASE_PATH
from app.models.domain import AppSettings
from app.models.persistence import ProjectRecord
from app.models.project_state import PathValidation, ProjectState
from app.project import ProjectFile
from app.repositories.project_repository import ProjectRepository

PROJECT_SCHEMA_VERSION = 2


class ProjectManager:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database = Database(database_path)
        self.database.initialize()
        self.projects = ProjectRepository(self.database)
        self.current: ProjectState | None = None

    @property
    def current_project(self) -> ProjectState | None:
        return self.current

    def new_project(
        self,
        name: str,
        csv_path: Path | str | None = None,
        output_path: Path | str | None = None,
        provider: str = "mock",
        settings: AppSettings | None = None,
    ) -> ProjectState:
        project_settings = settings or AppSettings(provider=provider)
        project_settings = project_settings.model_copy(update={"provider": provider})
        record = self.projects.create(
            name=name.strip() or "Untitled project",
            provider=provider,
            settings=project_settings,
            csv_path=self._path_to_str(csv_path),
            output_path=self._path_to_str(output_path),
        )
        self.current = self._state_from_record(record, dirty=True)
        return self.current

    def open_project(self, path: Path | str) -> ProjectState:
        project_path = Path(path)
        try:
            raw = json.loads(project_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed project file: {project_path}") from exc
        except OSError as exc:
            raise ValueError(f"Could not read project file: {project_path}") from exc

        state = self._state_from_project_json(raw, project_path)
        existing = self.projects.get_by_project_file(str(project_path))
        if existing:
            record = self.projects.update(
                existing.id,
                name=state.name,
                project_file=str(project_path),
                csv_path=self._path_to_str(state.csv_path),
                output_path=self._path_to_str(state.output_path),
                provider=state.provider,
                settings=state.settings,
            )
        else:
            record = self.projects.create(
                name=state.name,
                project_file=str(project_path),
                csv_path=self._path_to_str(state.csv_path),
                output_path=self._path_to_str(state.output_path),
                provider=state.provider,
                settings=state.settings,
            )
        if record is None:
            raise ValueError(f"Could not synchronize project: {project_path}")
        self.projects.touch_last_opened(record.id)
        refreshed = self.projects.get_by_id(record.id)
        self.current = self._state_from_record(refreshed or record, dirty=False)
        return self.current

    def save_project(self) -> ProjectState:
        if self.current is None:
            raise ValueError("No project is open.")
        if self.current.project_file is None:
            raise ValueError("Project has no file path. Use save_project_as().")
        self._write_project_file(self.current.project_file, self.current)
        self._sync_current()
        self.projects.touch_last_opened(self.current.project_id)
        self.current.dirty = False
        self.current.last_saved_at = utc_now()
        return self.current

    def save_project_as(self, path: Path | str) -> ProjectState:
        if self.current is None:
            raise ValueError("No project is open.")
        target = Path(path)
        if target.suffix.lower() != ".stproj":
            target = target.with_suffix(".stproj")
        self.current.project_file = target
        self._write_project_file(target, self.current)
        self._sync_current()
        self.projects.touch_last_opened(self.current.project_id)
        self.current.dirty = False
        self.current.last_saved_at = utc_now()
        return self.current

    def close_project(self) -> None:
        self.current = None

    def mark_dirty(self) -> None:
        if self.current is not None:
            self.current.dirty = True

    def update_csv_path(self, path: Path | str | None) -> None:
        if self.current is not None:
            self.current.csv_path = self._path_or_none(path)
            self.mark_dirty()
            self._sync_current()

    def update_output_path(self, path: Path | str | None) -> None:
        if self.current is not None:
            self.current.output_path = self._path_or_none(path)
            self.mark_dirty()
            self._sync_current()

    def update_provider(self, provider: str) -> None:
        if self.current is not None and self.current.provider != provider:
            self.current.provider = provider
            self.current.settings = self.current.settings.model_copy(update={"provider": provider})
            self.mark_dirty()
            self._sync_current()

    def update_settings(self, settings: AppSettings) -> None:
        if self.current is not None:
            self.current.settings = settings
            self.current.provider = settings.provider
            self.mark_dirty()
            self._sync_current()

    def list_recent_projects(self, limit: int = 10) -> list[ProjectRecord]:
        return self.projects.list_recent(limit)

    def remove_recent_project(self, project_id: int) -> None:
        self.projects.remove_from_recent(project_id)

    def validate_current_paths(self) -> PathValidation:
        if self.current is None:
            return PathValidation()
        missing_csv = bool(self.current.csv_path and not self.current.csv_path.exists())
        missing_output = bool(self.current.output_path and not self.current.output_path.exists())
        return PathValidation(missing_csv=missing_csv, missing_output=missing_output)

    def autosave_if_needed(self, generation_active: bool = False) -> bool:
        if generation_active or self.current is None:
            return False
        if not self.current.dirty or self.current.project_file is None:
            return False
        self.save_project()
        return True

    def _sync_current(self) -> None:
        if self.current is None or self.current.project_id is None:
            return
        record = self.projects.update(
            self.current.project_id,
            name=self.current.name,
            project_file=self._path_to_str(self.current.project_file),
            csv_path=self._path_to_str(self.current.csv_path),
            output_path=self._path_to_str(self.current.output_path),
            provider=self.current.provider,
            settings=self.current.settings,
        )
        if record is not None:
            self.current.updated_at = record.updated_at

    def _state_from_record(self, record: ProjectRecord, dirty: bool) -> ProjectState:
        settings = AppSettings.model_validate_json(record.settings_json)
        return ProjectState(
            project_id=record.id,
            name=record.name,
            project_file=self._path_or_none(record.project_file),
            csv_path=self._path_or_none(record.csv_path),
            output_path=self._path_or_none(record.output_path),
            provider=record.provider,
            settings=settings,
            created_at=record.created_at,
            updated_at=record.updated_at,
            dirty=dirty,
        )

    def _state_from_project_json(self, raw: dict[str, Any], path: Path) -> ProjectState:
        settings_raw = raw.get("settings") or {}
        settings = AppSettings.model_validate(settings_raw)
        provider = raw.get("provider") or settings.provider or "mock"
        settings = settings.model_copy(update={"provider": provider})
        return ProjectState(
            project_id=None,
            name=raw.get("name") or path.stem,
            project_file=path,
            csv_path=self._path_or_none(raw.get("csv_path")),
            output_path=self._path_or_none(raw.get("output_path")),
            provider=provider,
            settings=settings,
            dirty=False,
        )

    def _write_project_file(self, path: Path, state: ProjectState) -> None:
        project = ProjectFile(
            version=PROJECT_SCHEMA_VERSION,
            name=state.name,
            csv_path=self._path_to_str(state.csv_path) or "",
            output_path=self._path_to_str(state.output_path) or "",
            settings=state.settings,
        )
        payload = json.loads(project.model_dump_json())
        payload["project_id"] = state.project_id
        payload["provider"] = state.provider
        payload["schema_version"] = PROJECT_SCHEMA_VERSION
        data = json.dumps(payload, indent=2, ensure_ascii=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.write("\n")
            Path(temp_name).replace(path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _path_or_none(path: Path | str | None) -> Path | None:
        if path is None or str(path) == "":
            return None
        return Path(path)

    @staticmethod
    def _path_to_str(path: Path | str | None) -> str | None:
        if path is None or str(path) == "":
            return None
        return str(path)
