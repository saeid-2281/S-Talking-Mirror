from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


GIT_CREDENTIALS = re.compile(r"(https?://)([^/@\s]+)@")
FORBIDDEN_COMMIT_PATTERNS = (
    "settings.json",
    ".venv/",
    ".venv\\",
    "reports/",
    "reports\\",
    "artifacts/",
    "artifacts\\",
    "logs/",
    "logs\\",
    "cache/",
    "cache\\",
    ".egg-info/",
    ".egg-info\\",
)
FORBIDDEN_SUFFIXES = (".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".mp3", ".wav", ".pcm")


@dataclass(frozen=True)
class GitStatus:
    branch: str
    clean: bool
    changed_files: list[str]


class GitService:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def current_branch(self) -> str:
        output = self._run(["branch", "--show-current"], check=False).strip()
        if not output or "fatal:" in output.lower():
            return "unknown"
        return output

    def status(self) -> GitStatus:
        files = self.changed_files()
        return GitStatus(branch=self.current_branch(), clean=not files, changed_files=files)

    def changed_files(self) -> list[str]:
        output = self._run(["status", "--porcelain"], check=False)
        if "not a git repository" in output.lower():
            return []
        files: list[str] = []
        for line in output.splitlines():
            if len(line) > 3:
                files.append(line[3:].strip())
        return files

    def recent_commits(self, limit: int = 5) -> list[str]:
        output = self._run(["log", f"-{limit}", "--oneline"], check=False)
        return output.splitlines()

    def remote_summary(self) -> list[str]:
        output = self._run(["remote", "-v"], check=False)
        return [self.sanitize_text(line) for line in output.splitlines()]

    def ahead_behind(self) -> str:
        output = self._run(["status", "-sb"], check=False).splitlines()
        return self.sanitize_text(output[0]) if output else ""

    def prepare_commit(self, message: str = "feat(devtools): add complete diagnostics and development assistant") -> dict:
        branch = self.current_branch()
        files = self.changed_files()
        blocked = self._blocked_files(files)
        return {
            "branch": branch,
            "allowed": branch != "main" and not blocked,
            "message": message,
            "changed_files": files,
            "blocked_files": blocked,
        }

    def commit(self, message: str) -> str:
        preview = self.prepare_commit(message)
        if preview["branch"] == "main":
            raise RuntimeError("Refusing to commit on main")
        if preview["blocked_files"]:
            raise RuntimeError(f"Refusing to commit blocked files: {preview['blocked_files']}")
        self._run_checks()
        self._run(["add", "."])
        return self._run(["commit", "-m", message])

    def push_current_branch(self) -> str:
        branch = self.current_branch()
        if branch == "main":
            raise RuntimeError("Refusing to push main")
        return self._run(["push", "origin", branch])

    def generate_pr_description(self) -> str:
        status = self.status()
        commits = "\n".join(f"- {commit}" for commit in self.recent_commits())
        files = "\n".join(f"- {file}" for file in status.changed_files) or "- No local changes"
        return (
            "## Summary\n"
            "- Adds complete diagnostics and development assistant workflow.\n\n"
            "## Branch\n"
            f"- {status.branch}\n\n"
            "## Recent Commits\n"
            f"{commits}\n\n"
            "## Changed Files\n"
            f"{files}\n\n"
            "## Validation\n"
            "- Run `scripts/dev-check.ps1` before merging.\n"
        )

    def sanitize_text(self, value: str) -> str:
        return GIT_CREDENTIALS.sub(r"\1[REDACTED]@", value)

    def _blocked_files(self, files: list[str]) -> list[str]:
        blocked: list[str] = []
        for file in files:
            normalized = file.replace("\\", "/")
            if normalized.endswith(FORBIDDEN_SUFFIXES) or any(pattern.replace("\\", "/") in normalized for pattern in FORBIDDEN_COMMIT_PATTERNS):
                blocked.append(file)
        return blocked

    def _run(self, args: list[str], *, check: bool = True) -> str:
        if any(arg in {"merge", "reset", "clean", "checkout", "restore"} for arg in args):
            raise RuntimeError(f"Refusing destructive git command: {' '.join(args)}")
        if any(arg.startswith("--force") or arg == "-f" for arg in args):
            raise RuntimeError("Refusing force operation")
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        output = f"{result.stdout}{result.stderr}"
        if check and result.returncode != 0:
            raise RuntimeError(self.sanitize_text(output.strip()))
        return self.sanitize_text(output)

    def _run_checks(self) -> None:
        script = self.repo_root / "scripts" / "dev-check.ps1"
        if not script.exists():
            raise RuntimeError("Development check script not found")
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(self.sanitize_text(f"Checks failed:\n{result.stdout}{result.stderr}"))
