from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.models.workspace_profile import WorkspaceProfile


class WorkspaceProfileService:
    """Owns built-in workspace profiles and the last selected profile."""

    BUILT_INS = (
        WorkspaceProfile("Compact", False, False, False, 96, 0, 0, description="Queue-first compact workspace."),
        WorkspaceProfile("Standard", True, True, False, 144, 290, 330, 0, description="Balanced everyday workspace."),
        WorkspaceProfile("Generation", True, True, True, 176, 300, 340, 1, description="Monitor-focused generation workspace."),
        WorkspaceProfile("Wide", True, True, True, 176, 320, 340, 1, description="Expanded three-panel workspace."),
        WorkspaceProfile("Review", False, True, True, 176, 0, 360, 0, description="Queue and selected-row review workspace."),
        WorkspaceProfile("Debug", True, True, True, 220, 320, 360, 1, description="Expanded diagnostics and activity workspace."),
        WorkspaceProfile("Focus Mode", False, False, False, 96, 0, 0, description="Queue and generation controls only."),
    )

    def __init__(self, state_path: Path) -> None:
        self.state_path = Path(state_path)
        self._profiles = {profile.name: profile for profile in self.BUILT_INS}
        self._last_profile = "Standard"
        self._load()

    def names(self) -> tuple[str, ...]:
        return tuple(self._profiles)

    def get(self, name: str) -> WorkspaceProfile:
        return self._profiles.get(name, self._profiles["Standard"])

    @property
    def last_profile(self) -> str:
        return self._last_profile if self._last_profile in self._profiles else "Standard"

    def select(self, name: str) -> WorkspaceProfile:
        profile = self.get(name)
        self._last_profile = profile.name
        self._save()
        return profile

    def restore_default(self) -> WorkspaceProfile:
        return self.select("Standard")

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            last = str(payload.get("last_profile", "Standard"))
            if last in self._profiles:
                self._last_profile = last
        except (OSError, ValueError, TypeError):
            self._last_profile = "Standard"

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_profile": self._last_profile,
            "profiles": [asdict(profile) for profile in self.BUILT_INS],
        }
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
