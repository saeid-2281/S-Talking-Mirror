from __future__ import annotations


STATUS_COLORS = {
    "ready": "#22C55E",
    "running": "#38BDF8",
    "paused": "#F59E0B",
    "stopping": "#F59E0B",
    "stopped by user": "#EF4444",
    "finished": "#22C55E",
    "failed": "#EF4444",
    "completed": "#22C55E",
    "pending": "#60A5FA",
    "skipped": "#94A3B8",
}


def format_duration(seconds: float | int | None, *, empty_zero: bool = False) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(round(float(seconds))))
    if total == 0 and empty_zero:
        return "—"
    if total < 60:
        return f"{total} s"
    minutes, remaining = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {remaining} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def format_files_per_minute(value: float | int | None) -> str:
    if value is None or float(value) <= 0:
        return "—"
    rounded = round(float(value), 2)
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def format_characters_per_minute(value: float | int | None) -> str:
    if value is None or float(value) <= 0:
        return "—"
    return f"{int(round(float(value))):,}"


def elide_middle(value: str | None, max_chars: int = 44) -> str:
    text = value or ""
    if len(text) <= max_chars:
        return text or "—"
    if max_chars <= 3:
        return "..."[:max_chars]
    left = max(1, (max_chars - 3) // 2)
    right = max(1, max_chars - 3 - left)
    return f"{text[:left]}...{text[-right:]}"


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status.strip().lower(), "#94A3B8")
