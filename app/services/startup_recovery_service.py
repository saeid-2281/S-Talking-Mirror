from __future__ import annotations

import json
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.database.connection import Database
from app.models import SessionRestoreState, StartupRecoveryState
from app.repositories import JobRepository, ProjectRepository


class StartupRecoveryService:
    def __init__(
        self,
        runtime: RuntimeConfig,
        database: Database,
        job_repository: JobRepository,
        project_repository: ProjectRepository,
    ) -> None:
        self.runtime = runtime
        self.database = database
        self.job_repository = job_repository
        self.project_repository = project_repository

    def recover(self) -> StartupRecoveryState:
        state = StartupRecoveryState()
        state.temporary_files_removed = self.clean_stale_temporary_audio()
        try:
            self.database.initialize()
        except Exception as exc:
            state.database_ok = False
            state.migrations_ok = False
            state.messages.append(f"Database migration validation failed: {exc}")
        else:
            state.running_jobs_recovered = self.job_repository.reset_all_interrupted()
        if self.runtime.settings_path.exists():
            try:
                json.loads(self.runtime.settings_path.read_text(encoding="utf-8"))
            except Exception:
                state.malformed_settings_recovered = True
        for record in self.project_repository.list_recent(25):
            if record.project_file and not Path(record.project_file).exists():
                state.stale_recent_projects.append(record.project_file)
        return state

    def clean_stale_temporary_audio(self) -> int:
        roots = [self.runtime.default_output_dir, self.runtime.cache_dir, self.runtime.artifacts_dir]
        patterns = ["*.tmp", "*.part", "*.partial", "s_talking_*.wav", "s_talking_*.mp3"]
        removed = 0
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                for path in root.rglob(pattern):
                    if not path.is_file():
                        continue
                    try:
                        path.unlink()
                    except OSError:
                        continue
                    removed += 1
        return removed


class SessionRestoreService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime
        self.path = runtime.cache_dir / "session-restore.json"

    def load(self) -> SessionRestoreState:
        if not self.path.exists():
            return SessionRestoreState(auto_restore_enabled=True)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return SessionRestoreState(auto_restore_enabled=True, message="Ignored malformed session restore data.")
        project = payload.get("last_project_path")
        return SessionRestoreState(
            auto_restore_enabled=bool(payload.get("auto_restore_enabled", True)),
            last_project_path=Path(project) if project else None,
            queue_filter=str(payload.get("queue_filter") or "all"),
            selected_row=int(payload["selected_row"]) if payload.get("selected_row") is not None else None,
        )

    def save(
        self,
        *,
        last_project_path: Path | None,
        auto_restore_enabled: bool = True,
        queue_filter: str = "all",
        selected_row: int | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "auto_restore_enabled": auto_restore_enabled,
            "last_project_path": str(last_project_path) if last_project_path else None,
            "queue_filter": queue_filter,
            "selected_row": selected_row,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
