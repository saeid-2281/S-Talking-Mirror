from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ICON_REGISTRY: dict[str, str] = {
    "add": "M12 5v14M5 12h14",
    "new": "M12 5v14M5 12h14",
    "remove": "M5 12h14",
    "edit": "M4 17.5V20h2.5L18 8.5 15.5 6 4 17.5Z M14.5 7 17 9.5",
    "delete": "M6 7h12M9 7V5h6v2M8 10v9h8v-9",
    "copy": "M8 8h10v10H8z M5 5h10v3H8v7H5z",
    "open": "M4 7h6l2 3h8v9H4z M4 10h16",
    "folder": "M3 7h7l2 3h9v9H3z",
    "save": "M5 4h12l2 2v14H5z M8 4v6h8M8 20v-6h8v6",
    "refresh": "M19 8v5h-5M5 16v-5h5M18 13a6 6 0 0 0-10-5M6 11a6 6 0 0 0 10 5",
    "search": "M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13ZM16 16l5 5",
    "filter": "M4 5h16l-6 7v6l-4 2v-8z",
    "sort": "M8 5v14M5 8l3-3 3 3M16 19V5M13 16l3 3 3-3",
    "play": "M8 5v14l11-7z",
    "pause": "M7 5h4v14H7z M14 5h4v14h-4z",
    "stop": "M7 7h10v10H7z",
    "retry": "M19 8v5h-5M5 16v-5h5M18 13a6 6 0 0 0-10-5M6 11a6 6 0 0 0 10 5",
    "skip": "M6 6l7 6-7 6z M14 6h4v12h-4z",
    "reset": "M7 7h10v10H7z M9 4h6M9 20h6",
    "favorite-outline": "M12 4l2.4 5 5.6.8-4 3.9.9 5.5L12 16l-5 2.7.9-5.5-4-3.9 5.6-.8z",
    "favorite-filled": "M12 4l2.4 5 5.6.8-4 3.9.9 5.5L12 16l-5 2.7.9-5.5-4-3.9 5.6-.8z",
    "voice": "M7 10a5 5 0 0 1 10 0v2a5 5 0 0 1-10 0z M12 17v4M8 21h8",
    "waveform": "M4 12h3l2-7 4 14 3-10 2 3h2",
    "provider/account": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21a8 8 0 0 1 16 0",
    "model": "M5 5h14v14H5z M9 9h6v6H9z M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3",
    "language": "M4 5h10M9 5c-.5 5-2 8-5 11M6 10h8M11 10c1 3 3 5 5 6M15 20l4-10 4 10M16.5 17h5",
    "dictionary": "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z M8 4v13a3 3 0 0 0 3 3",
    "settings": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1",
    "project": "M4 6h6l2 3h8v11H4z",
    "queue": "M5 7h14M5 12h14M5 17h14",
    "report": "M6 4h9l3 3v13H6z M14 4v4h4M9 12h6M9 16h6",
    "notification": "M7 18h10M9 18a3 3 0 0 0 6 0M8 9a4 4 0 0 1 8 0v4l2 3H6l2-3z",
    "activity": "M4 12h4l2-6 4 12 2-6h4",
    "history": "M4 12a8 8 0 1 0 3-6M4 4v6h6M12 8v5l4 2",
    "health": "M12 21s-8-4.8-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 6.2-8 11-8 11z",
    "warning": "M12 4 22 20H2z M12 9v5M12 17h.01",
    "error": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM8 8l8 8M16 8l-8 8",
    "success": "M20 6 9 17l-5-5",
    "info": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM12 10v7M12 7h.01",
    "more": "M5 12h.01M12 12h.01M19 12h.01",
    "chevron-up": "M6 15l6-6 6 6",
    "chevron-down": "M6 9l6 6 6-6",
    "chevron-left": "M15 6l-6 6 6 6",
    "chevron-right": "M9 6l6 6-6 6",
}

ALIASES = {
    "start": "play",
    "up": "chevron-up",
    "down": "chevron-down",
    "provider": "provider/account",
}


def icon(name: str, *, size: int = 20, color: str | None = None) -> QIcon:
    app = QApplication.instance()
    if app is None:
        return QIcon()
    path = ICON_REGISTRY.get(name) or ICON_REGISTRY.get(ALIASES.get(name, ""), ICON_REGISTRY["project"])
    stroke = color or app.palette().buttonText().color().name()
    fill = stroke if name == "favorite-filled" else "none"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    return QIcon(pixmap)


def required_icon_names() -> set[str]:
    return set(ICON_REGISTRY)
