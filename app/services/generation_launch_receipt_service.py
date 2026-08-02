from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models.generation_launch_receipt import (
    GenerationLaunchReceipt,
    GenerationLaunchReceiptSummary,
)


class GenerationLaunchReceiptService:
    """Discover, verify, filter, summarize, and export launch receipts."""

    RECEIPT_NAME = "generation-launch.json"
    MARKDOWN_NAME = "generation-launch.md"

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = Path(reports_dir)

    def list_receipts(
        self,
        *,
        project_name: str | None = None,
        provider: str | None = None,
        integrity_status: str | None = None,
        risk_level: str | None = None,
        search: str = "",
        limit: int = 500,
    ) -> list[GenerationLaunchReceipt]:
        receipts = [self.load(path) for path in self._receipt_paths()]
        project_key = str(project_name or "").strip().casefold()
        provider_key = str(provider or "").strip().casefold()
        integrity_key = str(integrity_status or "").strip().casefold()
        risk_key = str(risk_level or "").strip().casefold()
        search_key = str(search or "").strip().casefold()

        filtered: list[GenerationLaunchReceipt] = []
        for receipt in receipts:
            if project_key and receipt.project_name.casefold() != project_key:
                continue
            if provider_key and receipt.provider.casefold() != provider_key:
                continue
            if integrity_key and receipt.integrity_status.casefold() != integrity_key:
                continue
            if risk_key and receipt.risk_level.casefold() != risk_key:
                continue
            if search_key and search_key not in self._search_text(receipt):
                continue
            filtered.append(receipt)

        filtered.sort(key=lambda item: (item.created_at, str(item.path)), reverse=True)
        return filtered[: max(0, int(limit))]

    def latest(self, *, project_name: str | None = None) -> GenerationLaunchReceipt | None:
        records = self.list_receipts(project_name=project_name, limit=1)
        return records[0] if records else None

    def load(self, path: Path) -> GenerationLaunchReceipt:
        receipt_path = Path(path)
        markdown_path = receipt_path.with_name(self.MARKDOWN_NAME)
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Receipt root must be a JSON object.")
        except Exception as exc:
            return self._unreadable(receipt_path, markdown_path, str(exc))

        integrity_status, integrity_message = self.verify_payload(payload)
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        plan = payload.get("generation_plan") if isinstance(payload.get("generation_plan"), dict) else {}
        return GenerationLaunchReceipt(
            path=receipt_path,
            markdown_path=markdown_path,
            schema_version=self._integer(payload.get("schema_version"), 1),
            receipt_id=str(payload.get("receipt_id") or ""),
            created_at=str(payload.get("created_at") or self._mtime(receipt_path)),
            project_name=str(payload.get("project_name") or receipt_path.parents[2].name),
            launch_fingerprint=str(payload.get("launch_fingerprint") or ""),
            preflight_status=str(payload.get("preflight_status") or "unknown"),
            review_status=str(payload.get("review_status") or "unknown"),
            provider=str(settings.get("provider") or "unknown"),
            model_id=str(settings.get("model_id") or ""),
            voice_id=str(settings.get("voice_id") or ""),
            output_directory=str(payload.get("output_directory") or ""),
            files=self._integer(scope.get("files")),
            characters=self._integer(scope.get("characters")),
            provider_requests=self._integer(scope.get("provider_requests")),
            existing_outputs=self._integer(scope.get("existing_outputs")),
            risk_level=str(plan.get("risk_level") or "unknown"),
            estimated_cost=self._number(plan.get("estimated_cost")),
            currency=str(plan.get("currency") or "USD").upper(),
            acknowledged_codes=self._strings(payload.get("acknowledged_codes")),
            required_acknowledgements=self._strings(
                payload.get("required_acknowledgements")
            ),
            integrity_status=integrity_status,
            integrity_message=integrity_message,
        )

    @classmethod
    def canonical_digest(cls, payload: dict[str, object]) -> str:
        canonical = dict(payload)
        canonical.pop("integrity", None)
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def verify_payload(cls, payload: dict[str, object]) -> tuple[str, str]:
        schema_version = cls._integer(payload.get("schema_version"), 1)
        integrity = payload.get("integrity")
        if schema_version < 2 and not isinstance(integrity, dict):
            return "legacy", "Receipt predates integrity metadata."
        if not isinstance(integrity, dict):
            return "mismatch", "Integrity metadata is missing."
        algorithm = str(integrity.get("algorithm") or "").casefold()
        expected = str(integrity.get("digest") or "").casefold()
        if algorithm != "sha256" or not expected:
            return "mismatch", "Integrity metadata is incomplete or unsupported."
        actual = cls.canonical_digest(payload)
        if actual != expected:
            return "mismatch", "Receipt content no longer matches its SHA-256 digest."
        return "verified", "Receipt content matches its SHA-256 digest."

    @staticmethod
    def summary(records: Iterable[GenerationLaunchReceipt]) -> GenerationLaunchReceiptSummary:
        receipts = list(records)
        return GenerationLaunchReceiptSummary(
            receipt_count=len(receipts),
            verified_count=sum(item.integrity_status == "verified" for item in receipts),
            legacy_count=sum(item.integrity_status == "legacy" for item in receipts),
            mismatch_count=sum(item.integrity_status == "mismatch" for item in receipts),
            unreadable_count=sum(item.integrity_status == "unreadable" for item in receipts),
            high_risk_count=sum(item.risk_level == "high" for item in receipts),
            confirmation_required_count=sum(
                item.review_status == "confirmation_required" for item in receipts
            ),
            total_files=sum(max(0, item.files) for item in receipts),
            total_characters=sum(max(0, item.characters) for item in receipts),
        )

    @staticmethod
    def export(
        records: Iterable[GenerationLaunchReceipt],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        receipts = list(records)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "launches"
        json_path = target / f"generation-launch-receipts-{safe_name}-{stamp}.json"
        csv_path = target / f"generation-launch-receipts-{safe_name}-{stamp}.csv"
        summary = GenerationLaunchReceiptService.summary(receipts)
        rows = [GenerationLaunchReceiptService._export_row(item) for item in receipts]
        json_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "summary": summary.__dict__,
                    "receipts": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fieldnames = list(rows[0]) if rows else list(
            GenerationLaunchReceiptService._export_row(
                GenerationLaunchReceipt(Path(""), Path(""))
            )
        )
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path

    def _receipt_paths(self) -> list[Path]:
        if not self.reports_dir.exists():
            return []
        return [path for path in self.reports_dir.rglob(self.RECEIPT_NAME) if path.is_file()]

    @staticmethod
    def _search_text(receipt: GenerationLaunchReceipt) -> str:
        return " ".join(
            (
                receipt.receipt_id,
                receipt.project_name,
                receipt.launch_fingerprint,
                receipt.provider,
                receipt.model_id,
                receipt.voice_id,
                receipt.output_directory,
                receipt.preflight_status,
                receipt.review_status,
                receipt.risk_level,
                receipt.integrity_status,
            )
        ).casefold()

    @staticmethod
    def _unreadable(path: Path, markdown_path: Path, message: str) -> GenerationLaunchReceipt:
        try:
            project_name = path.parents[2].name
        except IndexError:
            project_name = "unknown"
        return GenerationLaunchReceipt(
            path=path,
            markdown_path=markdown_path,
            created_at=GenerationLaunchReceiptService._mtime(path),
            project_name=project_name,
            integrity_status="unreadable",
            integrity_message=f"Receipt could not be read: {message}",
        )

    @staticmethod
    def _export_row(receipt: GenerationLaunchReceipt) -> dict[str, object]:
        return {
            "receipt_id": receipt.receipt_id,
            "created_at": receipt.created_at,
            "project_name": receipt.project_name,
            "launch_fingerprint": receipt.launch_fingerprint,
            "preflight_status": receipt.preflight_status,
            "review_status": receipt.review_status,
            "provider": receipt.provider,
            "model_id": receipt.model_id,
            "voice_id": receipt.voice_id,
            "files": receipt.files,
            "characters": receipt.characters,
            "provider_requests": receipt.provider_requests,
            "existing_outputs": receipt.existing_outputs,
            "risk_level": receipt.risk_level,
            "estimated_cost": receipt.estimated_cost,
            "currency": receipt.currency,
            "acknowledged_codes": ";".join(receipt.acknowledged_codes),
            "required_acknowledgements": ";".join(receipt.required_acknowledgements),
            "integrity_status": receipt.integrity_status,
            "integrity_message": receipt.integrity_message,
            "receipt_path": str(receipt.path),
            "markdown_path": str(receipt.markdown_path),
            "output_directory": receipt.output_directory,
        }

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(item) for item in value if str(item).strip())

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _mtime(path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            return ""
