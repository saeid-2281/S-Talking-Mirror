from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TASK_STATUSES = ["Draft", "Ready", "In Progress", "Review", "Done"]


@dataclass(frozen=True)
class TaskPrompt:
    path: Path
    title: str
    branch: str
    goal: str
    acceptance_criteria: str
    codex_prompt: str
    status: str


class TaskPromptService:
    def __init__(self, repo_root: Path) -> None:
        self.tasks_dir = repo_root / "docs" / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> list[Path]:
        return sorted(self.tasks_dir.glob("*.md"))

    def load(self, path: Path) -> TaskPrompt:
        text = path.read_text(encoding="utf-8")
        return TaskPrompt(
            path=path,
            title=self._section(text, "Title") or path.stem,
            branch=self._section(text, "Branch"),
            goal=self._section(text, "Goal"),
            acceptance_criteria=self._section(text, "Acceptance Criteria"),
            codex_prompt=self._section(text, "Codex Prompt"),
            status=self._section(text, "Status") or "Draft",
        )

    def update_status(self, path: Path, status: str) -> None:
        if status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        text = path.read_text(encoding="utf-8")
        if "## Status" in text:
            before, marker, after = text.partition("## Status")
            remainder = after.split("\n## ", 1)
            tail = f"\n## {remainder[1]}" if len(remainder) > 1 else ""
            text = f"{before}{marker}\n{status}\n{tail}"
        else:
            text = f"{text.rstrip()}\n\n## Status\n{status}\n"
        path.write_text(text, encoding="utf-8")

    def _section(self, text: str, heading: str) -> str:
        marker = f"## {heading}"
        if marker not in text:
            return ""
        after = text.split(marker, 1)[1]
        body = after.split("\n## ", 1)[0]
        return body.strip()
