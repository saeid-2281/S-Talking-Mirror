from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class QtDialogLifecycleRecord:
    token: str
    class_name: str
    object_name: str = ""
    title: str = ""
    category: str = "report"
    state: str = "active"
    visible: bool = False
    modal: bool = False
    created_at: str = ""
    finished_at: str = ""
    result: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QtRuntimeHealthSnapshot:
    captured_at: str
    platform_name: str
    registered_active: int = 0
    hidden_registered: int = 0
    top_level_widgets: int = 0
    visible_top_levels: int = 0
    active_thread_count: int = 0
    peak_registered: int = 0
    created_total: int = 0
    finished_total: int = 0
    destroyed_total: int = 0
    stale_reference_count: int = 0
    records: tuple[QtDialogLifecycleRecord, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if self.stale_reference_count or self.hidden_registered:
            return "attention"
        return "healthy"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["status"] = self.status
        return payload
