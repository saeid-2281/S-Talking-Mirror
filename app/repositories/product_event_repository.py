from __future__ import annotations

import json

from app.database.connection import Database
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord


class ProductEventRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_notification(self, record: NotificationRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO notifications(
                    notification_id, severity, title, message, created_at, read,
                    action_label, action_payload
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.notification_id,
                    record.severity,
                    record.title,
                    record.message,
                    record.created_at,
                    int(record.read),
                    record.action_label,
                    record.action_payload,
                ),
            )

    def list_notifications(self, *, unread_only: bool = False, limit: int = 100) -> list[NotificationRecord]:
        where = "WHERE read = 0" if unread_only else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            NotificationRecord(
                notification_id=str(row["notification_id"]),
                severity=str(row["severity"]),
                title=str(row["title"]),
                message=str(row["message"]),
                created_at=str(row["created_at"]),
                read=bool(row["read"]),
                action_label=row["action_label"],
                action_payload=row["action_payload"],
            )
            for row in rows
        ]

    def mark_notification_read(self, notification_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE notifications SET read = 1 WHERE notification_id = ?", (notification_id,))

    def add_activity(self, event: ActivityEvent) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO activity_timeline(
                    event_id, project_id, category, title, message, created_at, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.category,
                    event.title,
                    event.message,
                    event.created_at,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

    def list_activity(self, *, project_id: int | None = None, limit: int = 200) -> list[ActivityEvent]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit) if project_id is not None else (limit,)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM activity_timeline {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            ActivityEvent(
                event_id=str(row["event_id"]),
                project_id=row["project_id"],
                category=str(row["category"]),
                title=str(row["title"]),
                message=str(row["message"]),
                created_at=str(row["created_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def add_batch_session(self, record: BatchSessionRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO batch_sessions(
                    session_id, project_id, scope, provider, model, voice,
                    total_jobs, completed_jobs, failed_jobs, skipped_jobs,
                    character_count, report_path, output_path, result, started_at, finished_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.project_id,
                    record.scope,
                    record.provider,
                    record.model,
                    record.voice,
                    record.total_jobs,
                    record.completed_jobs,
                    record.failed_jobs,
                    record.skipped_jobs,
                    record.character_count,
                    record.report_path,
                    record.output_path,
                    record.result,
                    record.started_at,
                    record.finished_at,
                ),
            )

    def list_batch_sessions(self, *, project_id: int | None = None, limit: int = 100) -> list[BatchSessionRecord]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit) if project_id is not None else (limit,)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM batch_sessions {where} ORDER BY started_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            BatchSessionRecord(
                session_id=str(row["session_id"]),
                project_id=row["project_id"],
                scope=str(row["scope"]),
                provider=str(row["provider"]),
                model=str(row["model"]),
                voice=str(row["voice"]),
                total_jobs=int(row["total_jobs"]),
                completed_jobs=int(row["completed_jobs"]),
                failed_jobs=int(row["failed_jobs"]),
                skipped_jobs=int(row["skipped_jobs"]),
                character_count=int(row["character_count"]),
                report_path=row["report_path"],
                output_path=row["output_path"],
                result=str(row["result"]),
                started_at=str(row["started_at"]),
                finished_at=row["finished_at"],
            )
            for row in rows
        ]
