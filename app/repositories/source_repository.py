from __future__ import annotations

import json
from pathlib import Path

from app.database.connection import Database
from app.models.project_source import ProjectSource, SourceColumnMapping, SourceImportStatus, SourceType


class ProjectSourceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_sources(self, project_id: int, sources: list[ProjectSource]) -> None:
        with self.database.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO project_sources(
                    source_id, project_id, display_name, source_type, source_path, worksheet_name,
                    enabled, import_order, detected_encoding, detected_delimiter, text_column,
                    filename_column, voice_column, model_column, language_column,
                    output_subfolder_column, row_start, row_end, imported_at, last_modified,
                    source_hash, import_status, valid_rows, rejected_rows, issue_count, settings_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    display_name = excluded.display_name,
                    source_type = excluded.source_type,
                    source_path = excluded.source_path,
                    worksheet_name = excluded.worksheet_name,
                    enabled = excluded.enabled,
                    import_order = excluded.import_order,
                    detected_encoding = excluded.detected_encoding,
                    detected_delimiter = excluded.detected_delimiter,
                    text_column = excluded.text_column,
                    filename_column = excluded.filename_column,
                    voice_column = excluded.voice_column,
                    model_column = excluded.model_column,
                    language_column = excluded.language_column,
                    output_subfolder_column = excluded.output_subfolder_column,
                    row_start = excluded.row_start,
                    row_end = excluded.row_end,
                    imported_at = excluded.imported_at,
                    last_modified = excluded.last_modified,
                    source_hash = excluded.source_hash,
                    import_status = excluded.import_status,
                    valid_rows = excluded.valid_rows,
                    rejected_rows = excluded.rejected_rows,
                    issue_count = excluded.issue_count,
                    settings_json = excluded.settings_json
                """,
                [self._row(ProjectSource(**{**source.__dict__, "project_id": project_id})) for source in sources],
            )

    def list_by_project(self, project_id: int) -> list[ProjectSource]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM project_sources
                WHERE project_id = ?
                ORDER BY import_order, display_name, worksheet_name
                """,
                (project_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def remove_source(self, source_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM project_sources WHERE source_id = ?", (source_id,))

    def save_snapshot(self, source_id: str, snapshot: dict[str, object], *, source_hash: str | None = None) -> None:
        from app.models.project_source import utc_now

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO source_import_snapshots(source_id, snapshot_json, created_at, source_hash)
                VALUES(?, ?, ?, ?)
                """,
                (source_id, json.dumps(snapshot, ensure_ascii=False), utc_now(), source_hash),
            )

    @staticmethod
    def _row(source: ProjectSource) -> tuple[object, ...]:
        return (
            source.source_id,
            source.project_id,
            source.display_name,
            source.source_type.value,
            str(source.source_path),
            source.worksheet_name,
            1 if source.enabled else 0,
            source.import_order,
            source.detected_encoding,
            source.detected_delimiter,
            source.mapping.text_column,
            source.mapping.filename_column,
            source.mapping.voice_column,
            source.mapping.model_column,
            source.mapping.language_column,
            source.mapping.output_subfolder_column,
            source.row_start,
            source.row_end,
            source.imported_at,
            source.last_modified,
            source.source_hash,
            source.import_status.value,
            source.valid_rows,
            source.rejected_rows,
            source.issue_count,
            "{}",
        )

    @staticmethod
    def _from_row(row) -> ProjectSource:
        return ProjectSource(
            source_id=str(row["source_id"]),
            project_id=row["project_id"],
            display_name=str(row["display_name"]),
            source_type=SourceType(str(row["source_type"])),
            source_path=Path(str(row["source_path"])),
            worksheet_name=row["worksheet_name"],
            enabled=bool(row["enabled"]),
            import_order=int(row["import_order"]),
            detected_encoding=row["detected_encoding"],
            detected_delimiter=row["detected_delimiter"],
            mapping=SourceColumnMapping(
                text_column=str(row["text_column"] or "text"),
                filename_column=str(row["filename_column"] or "filename"),
                voice_column=row["voice_column"],
                model_column=row["model_column"],
                language_column=row["language_column"],
                output_subfolder_column=row["output_subfolder_column"],
            ),
            row_start=int(row["row_start"] or 2),
            row_end=row["row_end"],
            imported_at=row["imported_at"],
            last_modified=row["last_modified"],
            source_hash=row["source_hash"],
            import_status=SourceImportStatus(str(row["import_status"] or "ready")),
            valid_rows=int(row["valid_rows"] or 0),
            rejected_rows=int(row["rejected_rows"] or 0),
            issue_count=int(row["issue_count"] or 0),
        )
