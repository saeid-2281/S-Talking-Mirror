from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app
from app.config.runtime import RuntimeConfig
from app.models.release_candidate import (
    ReleaseCandidateArtifact,
    ReleaseCandidateGate,
    ReleaseCandidateSnapshot,
)
from app.release import RELEASE_CHANNEL, SCHEMA_VERSION
from app.services.git_service import GitService
from app.services.release_readiness_service import ReleaseReadinessService


class ReleaseCandidateService:
    """Build and verify a reproducible source-portable release candidate."""

    MANIFEST_NAME = "release-candidate-manifest.json"
    CHECKSUM_NAME = "SHA256SUMS.txt"
    NOTES_NAME = "RELEASE-NOTES.md"
    RESULT_NAME = "release-candidate-result.json"
    REQUIRED_PACKAGE_PATHS = (
        "README.md",
        "pyproject.toml",
        "RUN-S-TALKING.bat",
        "app/__init__.py",
    )
    FORBIDDEN_ROOT_SEGMENTS = {
        ".git",
        ".venv",
        "artifacts",
        "reports",
        "output",
        "outputs",
        "logs",
        "cache",
        "credentials",
        "data",
    }
    FORBIDDEN_ANY_SEGMENTS = {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
    FORBIDDEN_NAMES = {
        ".env",
        "settings.json",
        "api-profiles.json",
        "workspace-profiles.json",
        "credentials.json",
        "secrets.json",
    }
    FORBIDDEN_SUFFIXES = {
        ".pyc",
        ".pyo",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mp3",
        ".wav",
        ".pcm",
    }

    def __init__(
        self,
        runtime: RuntimeConfig,
        git_service: GitService,
        readiness_service: ReleaseReadinessService | None = None,
        *,
        version: str | None = None,
        release_channel: str = RELEASE_CHANNEL,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.runtime = runtime
        self.git_service = git_service
        self.readiness_service = readiness_service
        self.version = str(version or app.__version__)
        self.release_channel = release_channel
        self.schema_version = int(schema_version)

    @property
    def candidate_root(self) -> Path:
        return self.runtime.artifacts_dir / "release-candidate"

    def latest_candidate_dir(self) -> Path:
        return self.candidate_root / "latest"

    def newest_package(self) -> Path | None:
        candidates = sorted(
            self.runtime.artifacts_dir.glob("package/*.zip"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def snapshot(self, package_path: Path | None = None) -> ReleaseCandidateSnapshot:
        package = Path(package_path) if package_path else self.newest_package()
        git = self.git_service.status()
        commit = self._current_commit()
        check = self._latest_release_check()
        pyproject_version = self._pyproject_version()
        audit = self.audit_package(package) if package else None
        gates = [
            self._gate(
                "git_clean",
                "Git working tree",
                git.clean,
                "blocker",
                "Working tree is clean." if git.clean else f"Uncommitted files: {', '.join(git.changed_files[:8])}",
                "Commit, restore, or back up local-only settings before creating a release candidate.",
            ),
            self._gate(
                "version_consistency",
                "Version consistency",
                self.normalize_version(pyproject_version) == self.normalize_version(self.version),
                "blocker",
                f"Runtime {self.version} · pyproject {pyproject_version or 'missing'}",
                "Align app/release.py and pyproject.toml before packaging.",
            ),
            self._gate(
                "release_channel",
                "Release channel",
                self.release_channel in {"rc", "stable"},
                "warning",
                f"Channel: {self.release_channel}",
                "Use rc or stable for a production candidate.",
            ),
            self._check_gate(check, "compileall", "Compileall"),
            self._check_gate(check, "ruff", "Ruff"),
            self._check_gate(check, "pytest", "Full pytest"),
            self._check_gate(check, "release_smoke", "Release smoke"),
            self._gate(
                "package_exists",
                "Portable package",
                package is not None and package.exists(),
                "blocker",
                str(package) if package else "No package ZIP found.",
                "Build a portable candidate before release approval.",
            ),
        ]
        artifacts: list[ReleaseCandidateArtifact] = []
        if package and package.exists():
            artifacts.append(self._artifact("portable_package", package, audit.status if audit else "unverified", audit.detail if audit else ""))
            gates.append(
                self._gate(
                    "package_structure",
                    "Package structure and privacy",
                    bool(audit and audit.status == "verified"),
                    "blocker",
                    audit.detail if audit else "Package audit unavailable.",
                    "Remove forbidden runtime, credential, cache, database, and output files from the ZIP.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "package_structure",
                    "Package structure and privacy",
                    False,
                    "blocker",
                    "No package available to audit.",
                    "Build and audit the portable candidate.",
                )
            )
        status = self._status(gates)
        summary = self._summary(status, gates)
        return ReleaseCandidateSnapshot(
            candidate_id=self._candidate_id(commit),
            version=self.version,
            release_channel=self.release_channel,
            schema_version=self.schema_version,
            branch=git.branch,
            commit=commit,
            captured_at=self._now(),
            status=status,
            summary=summary,
            test_count=int(check.get("steps", {}).get("pytest", {}).get("passed") or 0),
            package_path=package,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )

    def build_candidate(self) -> ReleaseCandidateSnapshot:
        if self.readiness_service is None:
            raise RuntimeError("Release readiness service is required to build a candidate.")
        package = self.readiness_service.create_portable_zip()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        candidate_dir = self.candidate_root / f"S-Talking-{self.version}-{stamp}"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        copied_package = candidate_dir / f"S-Talking-{self.version}-portable.zip"
        shutil.copy2(package, copied_package)
        audited = self.snapshot(copied_package)
        manifest_path, checksum_path, notes_path = self.create_manifest(audited, candidate_dir)
        manifest_artifact = self._artifact("release_manifest", manifest_path)
        checksum_artifact = self._artifact("checksums", checksum_path)
        notes_artifact = self._artifact("release_notes", notes_path)
        final = replace(
            audited,
            manifest_path=manifest_path,
            checksum_path=checksum_path,
            notes_path=notes_path,
            artifacts=audited.artifacts + (manifest_artifact, checksum_artifact, notes_artifact),
        )
        self._write_result(final, candidate_dir)
        self._publish_latest(candidate_dir)
        return final

    def create_manifest(
        self,
        snapshot: ReleaseCandidateSnapshot,
        directory: Path | None = None,
    ) -> tuple[Path, Path, Path]:
        folder = Path(directory or self.candidate_root / snapshot.candidate_id)
        folder.mkdir(parents=True, exist_ok=True)
        package = snapshot.package_path
        if package is None or not package.exists():
            raise FileNotFoundError("Release candidate package is missing.")
        artifact = self._artifact("portable_package", package)
        manifest = {
            "schema_version": 1,
            "candidate": snapshot.to_dict(),
            "package": artifact.to_dict(),
            "generated_at": self._now(),
        }
        manifest_path = folder / self.MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_hash = self._sha256(manifest_path)
        checksum_path = folder / self.CHECKSUM_NAME
        checksum_path.write_text(
            f"{artifact.sha256}  {package.name}\n{manifest_hash}  {manifest_path.name}\n",
            encoding="ascii",
        )
        notes_path = folder / self.NOTES_NAME
        notes_path.write_text(self._release_notes(snapshot), encoding="utf-8")
        return manifest_path, checksum_path, notes_path

    def verify_manifest(self, manifest_path: Path) -> tuple[bool, str]:
        path = Path(manifest_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            package_data = payload["package"]
            package = path.parent / Path(str(package_data["path"])).name
            if not package.exists():
                original = Path(str(package_data["path"]))
                package = original if original.exists() else package
            if not package.exists():
                return False, "Package referenced by the manifest is missing."
            expected = str(package_data["sha256"])
            actual = self._sha256(package)
            if actual != expected:
                return False, "Package SHA-256 does not match the manifest."
            audit = self.audit_package(package)
            if audit.status != "verified":
                return False, audit.detail
            return True, f"Manifest and package verified: {actual[:16]}…"
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"Manifest verification failed: {exc}"

    def audit_package(self, package_path: Path | None) -> ReleaseCandidateArtifact:
        if package_path is None:
            return ReleaseCandidateArtifact("portable_package", Path(), 0, "", "missing", "Package is missing.")
        path = Path(package_path)
        if not path.exists():
            return ReleaseCandidateArtifact("portable_package", path, 0, "", "missing", "Package is missing.")
        issues: list[str] = []
        try:
            with zipfile.ZipFile(path) as archive:
                raw_entries = [item.filename.replace("\\", "/") for item in archive.infolist() if not item.is_dir()]
                entries = self._strip_common_root(raw_entries)
                entry_set = set(entries)
                for entry in entries:
                    parts = [part for part in entry.split("/") if part]
                    lower_parts = [part.lower() for part in parts]
                    if ".." in parts or entry.startswith("/"):
                        issues.append(f"unsafe path: {entry}")
                    if (
                        (lower_parts and lower_parts[0] in self.FORBIDDEN_ROOT_SEGMENTS)
                        or any(part in self.FORBIDDEN_ANY_SEGMENTS for part in lower_parts)
                    ):
                        issues.append(f"forbidden directory: {entry}")
                    name = lower_parts[-1] if lower_parts else ""
                    suffix = Path(name).suffix.lower()
                    if name in self.FORBIDDEN_NAMES or suffix in self.FORBIDDEN_SUFFIXES:
                        issues.append(f"forbidden file: {entry}")
                missing = [required for required in self.REQUIRED_PACKAGE_PATHS if required not in entry_set]
                if missing:
                    issues.append("missing required: " + ", ".join(missing))
                bad_member = archive.testzip()
                if bad_member:
                    issues.append(f"corrupt member: {bad_member}")
        except (OSError, zipfile.BadZipFile) as exc:
            issues.append(f"invalid ZIP: {exc}")
        detail = "Package verified." if not issues else "; ".join(issues[:10])
        return self._artifact("portable_package", path, "verified" if not issues else "failed", detail)

    def export_snapshot(self, snapshot: ReleaseCandidateSnapshot, directory: Path | None = None) -> Path:
        folder = Path(directory or self.candidate_root / "exports")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"release-candidate-{snapshot.candidate_id}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def normalize_version(value: str) -> str:
        normalized = str(value or "").strip().lower().lstrip("v")
        normalized = re.sub(r"[-_.]?(rc|a|b)(\d+)$", r"\1\2", normalized)
        return normalized.replace("-", "")

    def _check_gate(self, check: dict[str, Any], code: str, label: str) -> ReleaseCandidateGate:
        step = check.get("steps", {}).get(code, {}) if check else {}
        passed = bool(check.get("success")) and bool(step.get("success"))
        if not check:
            detail = "No release-check result found."
        elif step:
            detail = f"Exit code {step.get('exit_code', 'unknown')}"
            if code == "pytest" and step.get("passed") is not None:
                detail += f" · {int(step.get('passed') or 0):,} passed"
        else:
            detail = "Step missing from release-check result."
        return self._gate(
            code,
            label,
            passed,
            "blocker",
            detail,
            "Run scripts/release-candidate.ps1 or scripts/release-check.ps1 successfully.",
        )

    @staticmethod
    def _gate(
        code: str,
        label: str,
        passed: bool,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> ReleaseCandidateGate:
        return ReleaseCandidateGate(
            code=code,
            label=label,
            status="passed" if passed else "failed",
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _status(gates: list[ReleaseCandidateGate]) -> str:
        if any(item.severity == "blocker" and item.status != "passed" for item in gates):
            return "blocked"
        if any(item.status != "passed" for item in gates):
            return "ready_with_warnings"
        return "ready"

    @staticmethod
    def _summary(status: str, gates: list[ReleaseCandidateGate]) -> str:
        blockers = sum(item.severity == "blocker" and item.status != "passed" for item in gates)
        warnings = sum(item.severity == "warning" and item.status != "passed" for item in gates)
        if status == "ready":
            return "Release candidate is verified and ready for final approval."
        if status == "ready_with_warnings":
            return f"Release candidate is viable with {warnings} warning(s)."
        return f"Release candidate is blocked by {blockers} release gate(s)."

    def _latest_release_check(self) -> dict[str, Any]:
        path = self.runtime.artifacts_dir / "release-check" / "latest" / "result.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _pyproject_version(self) -> str:
        path = self.runtime.app_root / "pyproject.toml"
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
            return str(payload.get("project", {}).get("version") or "")
        except (OSError, tomllib.TOMLDecodeError):
            return ""

    def _current_commit(self) -> str:
        commits = self.git_service.recent_commits(1)
        return commits[0].split()[0] if commits else "unknown"

    def _candidate_id(self, commit: str) -> str:
        seed = f"{self.version}|{self.release_channel}|{commit}|{self.schema_version}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:16]

    def _artifact(
        self,
        role: str,
        path: Path,
        status: str = "verified",
        detail: str = "",
    ) -> ReleaseCandidateArtifact:
        return ReleaseCandidateArtifact(
            role=role,
            path=Path(path),
            size_bytes=Path(path).stat().st_size if Path(path).exists() else 0,
            sha256=self._sha256(path) if Path(path).exists() else "",
            status=status,
            detail=detail,
        )

    @staticmethod
    def _strip_common_root(entries: list[str]) -> list[str]:
        if not entries:
            return []
        first_parts = [entry.split("/", 1)[0] for entry in entries if "/" in entry]
        if len(first_parts) == len(entries) and len(set(first_parts)) == 1:
            return [entry.split("/", 1)[1] for entry in entries]
        return entries

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _release_notes(self, snapshot: ReleaseCandidateSnapshot) -> str:
        gates = "\n".join(
            f"- [{'x' if gate.passed else ' '}] {gate.label}: {gate.detail}" for gate in snapshot.gates
        )
        return (
            f"# S-Talking {snapshot.version} Release Candidate\n\n"
            f"- Channel: `{snapshot.release_channel}`\n"
            f"- Commit: `{snapshot.commit}`\n"
            f"- Branch: `{snapshot.branch}`\n"
            f"- Database schema: `{snapshot.schema_version}`\n"
            f"- Test count: `{snapshot.test_count}`\n"
            f"- Candidate status: `{snapshot.status}`\n\n"
            "## Release gates\n\n"
            f"{gates}\n\n"
            "## Highlights\n\n"
            "- Unified preflight governance, launch receipts, approvals, run identity, output manifests, safe recovery, analytics, budget guard, retention, and Qt lifecycle hardening.\n\n"
            "## Known limitations\n\n"
            "- Provider-specific billing totals remain derived from configured launch pricing unless the provider exposes authoritative billing data.\n"
            "- Final clean-install and upgrade validation must be completed on the target Windows environment.\n\n"
            "## Rollback\n\n"
            "- Keep the previous portable package and restore the application data backup before replacing the candidate.\n"
        )

    def _write_result(self, snapshot: ReleaseCandidateSnapshot, candidate_dir: Path) -> Path:
        path = candidate_dir / self.RESULT_NAME
        path.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _publish_latest(self, candidate_dir: Path) -> None:
        latest = self.latest_candidate_dir()
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(candidate_dir, latest)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
