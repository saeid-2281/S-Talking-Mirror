from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.domain import AppSettings
from app.models.preview import PreviewRecord
from app.repositories.cache_repository import hash_settings, hash_text


class PreviewService:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def index_preview(
        self,
        *,
        provider: str,
        voice_id: str,
        model_id: str,
        preview_text: str,
        settings: AppSettings,
        file_path: Path,
        duration_seconds: float | None = None,
    ) -> PreviewRecord:
        record = PreviewRecord(
            provider=provider,
            voice_id=voice_id,
            model_id=model_id,
            preview_text=preview_text,
            text_hash=hash_text(preview_text),
            settings_hash=hash_settings(settings),
            file_path=file_path,
            created_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=duration_seconds,
            file_size=file_path.stat().st_size,
            last_played_at=None,
        )
        records = [
            item
            for item in self._load()
            if not (
                item.provider == provider
                and item.voice_id == voice_id
                and item.model_id == model_id
                and item.text_hash == record.text_hash
                and item.settings_hash == record.settings_hash
            )
        ]
        records.append(record)
        self._save(records)
        return record

    def list_for_voice(self, provider: str, voice_id: str) -> list[PreviewRecord]:
        records = [record for record in self._load_existing() if record.provider == provider and record.voice_id == voice_id]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def find_cached(self, provider: str, voice_id: str, model_id: str, text: str, settings: AppSettings) -> PreviewRecord | None:
        text_key = hash_text(text)
        settings_key = hash_settings(settings)
        for record in self._load_existing():
            if (
                record.provider == provider
                and record.voice_id == voice_id
                and record.model_id == model_id
                and record.text_hash == text_key
                and record.settings_hash == settings_key
            ):
                return record
        return None

    def mark_played(self, record: PreviewRecord) -> None:
        now = datetime.now(timezone.utc).isoformat()
        records = []
        for item in self._load_existing():
            if item.file_path == record.file_path:
                item = PreviewRecord(**{**asdict(item), "file_path": item.file_path, "last_played_at": now})
            records.append(item)
        self._save(records)

    def delete(self, record: PreviewRecord, *, delete_file: bool = True) -> None:
        records = [item for item in self._load_existing() if item.file_path != record.file_path]
        if delete_file:
            record.file_path.unlink(missing_ok=True)
        self._save(records)

    def clear_for_voice(self, provider: str, voice_id: str) -> int:
        records = self._load_existing()
        removed = [item for item in records if item.provider == provider and item.voice_id == voice_id]
        for item in removed:
            item.file_path.unlink(missing_ok=True)
        self._save([item for item in records if item not in removed])
        return len(removed)

    def _load_existing(self) -> list[PreviewRecord]:
        records = self._load()
        existing = [record for record in records if record.file_path.exists() and record.file_path.stat().st_size > 0]
        if len(existing) != len(records):
            self._save(existing)
        return existing

    def _load(self) -> list[PreviewRecord]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records: list[PreviewRecord] = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict):
                normalized = dict(item)
                normalized["file_path"] = Path(str(normalized.get("file_path", "")))
                try:
                    records.append(PreviewRecord(**normalized))
                except TypeError:
                    pass
        return records

    def _save(self, records: list[PreviewRecord]) -> None:
        payload: list[dict[str, Any]] = []
        for record in records:
            item = asdict(record)
            item["file_path"] = str(record.file_path)
            payload.append(item)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.index_path)
