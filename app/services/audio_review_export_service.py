from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

from app.models.audio_review_export import (
    AudioExportItem,
    AudioExportReceipt,
    AudioReviewItem,
    AudioReviewSummary,
)
from app.models.domain import AppSettings, JobStatus, TTSJob


class AudioReviewExportService:
    """Derive output-review state and copy verified audio artifacts safely.

    This layer is deliberately non-destructive: it never mutates source audio,
    never changes generation state, never transcodes, and never overwrites an
    existing export destination file. Exported copies are SHA-256 verified and
    described by a small manifest for handoff/audit purposes.
    """

    PRESET_FLAT = "flat"
    PRESET_PRESERVE = "preserve"

    def build_inventory(
        self,
        jobs: Iterable[TTSJob],
        output_dir: Path,
        settings: AppSettings,
        output_path_for: Callable[[TTSJob, Path, AppSettings], Path],
    ) -> AudioReviewSummary:
        items: list[AudioReviewItem] = []
        ready = missing = failed = pending = 0

        for job in jobs:
            path = Path(output_path_for(job, Path(output_dir), settings))
            exists = path.exists() and path.is_file()
            status = job.status.value
            if job.status == JobStatus.FAILED:
                review_status = "failed"
                failed += 1
            elif job.status == JobStatus.COMPLETED:
                if exists:
                    review_status = "ready"
                    ready += 1
                else:
                    review_status = "missing"
                    missing += 1
            else:
                review_status = "pending"
                pending += 1

            size = 0
            if exists:
                try:
                    size = max(0, int(path.stat().st_size))
                except OSError:
                    size = 0

            items.append(
                AudioReviewItem(
                    row_number=int(job.row_number),
                    filename=str(job.filename),
                    path=path,
                    job_status=status,
                    review_status=review_status,
                    size_bytes=size,
                )
            )

        return AudioReviewSummary(
            items=tuple(items),
            ready=ready,
            missing=missing,
            failed=failed,
            pending=pending,
        )

    def export(
        self,
        items: Iterable[AudioReviewItem],
        destination: Path,
        *,
        preset: str = PRESET_FLAT,
        output_root: Path | None = None,
    ) -> AudioExportReceipt:
        target_root = Path(destination)
        target_root.mkdir(parents=True, exist_ok=True)
        normalized_preset = (
            self.PRESET_PRESERVE
            if str(preset).strip().lower() == self.PRESET_PRESERVE
            else self.PRESET_FLAT
        )
        source_root = Path(output_root).resolve() if output_root else None

        copied: list[AudioExportItem] = []
        skipped_missing = 0
        collisions = 0

        for item in items:
            source = Path(item.path)
            if not item.ready or not source.exists() or not source.is_file():
                skipped_missing += 1
                continue

            relative = Path(source.name)
            if normalized_preset == self.PRESET_PRESERVE and source_root is not None:
                try:
                    relative = source.resolve().relative_to(source_root)
                except ValueError:
                    relative = Path(source.name)

            requested = target_root / relative
            requested.parent.mkdir(parents=True, exist_ok=True)
            destination_path, collided = self._collision_safe_path(requested)
            collisions += int(collided)
            shutil.copy2(source, destination_path)

            source_hash = self.sha256(source)
            destination_hash = self.sha256(destination_path)
            if destination_hash != source_hash:
                try:
                    destination_path.unlink()
                except OSError:
                    pass
                raise OSError(f"Export verification failed: {source}")

            copied.append(
                AudioExportItem(
                    row_number=item.row_number,
                    source_path=source,
                    destination_path=destination_path,
                    sha256=source_hash,
                    size_bytes=max(0, int(destination_path.stat().st_size)),
                )
            )

        manifest_path = self._write_manifest(
            target_root,
            normalized_preset,
            copied,
            skipped_missing=skipped_missing,
            collisions=collisions,
        )
        return AudioExportReceipt(
            destination=target_root,
            copied=tuple(copied),
            skipped_missing=skipped_missing,
            collisions_resolved=collisions,
            manifest_path=manifest_path,
        )

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _collision_safe_path(path: Path) -> tuple[Path, bool]:
        if not path.exists():
            return path, False
        stem = path.stem
        suffix = path.suffix
        index = 2
        while True:
            candidate = path.with_name(f"{stem}__{index}{suffix}")
            if not candidate.exists():
                return candidate, True
            index += 1

    def _write_manifest(
        self,
        destination: Path,
        preset: str,
        copied: list[AudioExportItem],
        *,
        skipped_missing: int,
        collisions: int,
    ) -> Path:
        requested = destination / "S-Talking-audio-export-manifest.json"
        manifest_path, _ = self._collision_safe_path(requested)
        payload = {
            "schema": 1,
            "product": "S-Talking",
            "operation": "audio_export_copy",
            "preset": preset,
            "copied": len(copied),
            "skipped_missing": int(skipped_missing),
            "collisions_resolved": int(collisions),
            "files": [
                {
                    "row_number": item.row_number,
                    "source": str(item.source_path),
                    "destination": str(item.destination_path),
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in copied
            ],
        }
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return manifest_path
