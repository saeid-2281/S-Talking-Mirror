from __future__ import annotations

import json
from typing import Any

from app.database.connection import Database
from app.database.migrations import utc_now
from app.models.domain import AppSettings
from app.models.persistence import ProjectRecord


def settings_to_json(settings: AppSettings | dict[str, Any] | str) -> str:
    if isinstance(settings, AppSettings):
        return settings.model_dump_json()
    if isinstance(settings, str):
        return settings
    return json.dumps(settings, ensure_ascii=False, sort_keys=True)


class ProjectRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        name: str,
        provider: str,
        settings: AppSettings | dict[str, Any] | str,
        project_file: str | None = None,
        csv_path: str | None = None,
        output_path: str | None = None,
    ) -> ProjectRecord:
        now = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects(
                    name, project_file, csv_path, output_path, provider,
                    settings_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    project_file,
                    csv_path,
                    output_path,
                    provider,
                    settings_to_json(settings),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return ProjectRecord.from_row(row)

    def get_by_id(self, project_id: int) -> ProjectRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return ProjectRecord.from_row(row) if row else None

    def get_by_project_file(self, project_file: str) -> ProjectRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_file = ?",
                (project_file,),
            ).fetchone()
        return ProjectRecord.from_row(row) if row else None

    def list_recent(self, limit: int = 10) -> list[ProjectRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM projects
                WHERE last_opened_at IS NOT NULL
                ORDER BY COALESCE(last_opened_at, updated_at, created_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [ProjectRecord.from_row(row) for row in rows]

    def update(self, project_id: int, **fields: Any) -> ProjectRecord | None:
        allowed = {
            "name",
            "project_file",
            "csv_path",
            "output_path",
            "provider",
            "settings",
            "settings_json",
            "last_opened_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "settings" in updates:
            updates["settings_json"] = settings_to_json(updates.pop("settings"))
        if not updates:
            return self.get_by_id(project_id)
        updates["updated_at"] = utc_now()

        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = [updates[key] for key in updates]
        values.append(project_id)
        with self.database.transaction() as connection:
            connection.execute(f"UPDATE projects SET {assignments} WHERE id = ?", values)
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return ProjectRecord.from_row(row) if row else None

    def touch_last_opened(self, project_id: int) -> None:
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE projects
                SET last_opened_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, project_id),
            )

    def delete(self, project_id: int) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def remove_from_recent(self, project_id: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE projects
                SET last_opened_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), project_id),
            )
