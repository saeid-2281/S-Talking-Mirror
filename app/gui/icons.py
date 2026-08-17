from __future__ import annotations

from PySide6.QtCore import QByteArray, QObject, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget

ICON_REGISTRY: dict[str, str] = {
    "add": "M12 5v14M5 12h14",
    "new": "M6 3h9l3 3v15H6z M14 3v4h4 M9 13h6 M12 10v6",
    "remove": "M5 12h14",
    "edit": "M4 17.5V20h2.5L18 8.5 15.5 6 4 17.5Z M14.5 7 17 9.5",
    "delete": "M6 7h12M9 7V5h6v2M8 10v9h8v-9",
    "copy": "M8 8h10v10H8z M5 5h10v3H8v7H5z",
    "open": "M4 7h6l2 3h8v9H4z M4 10h16",
    "folder": "M3 7h7l2 3h9v9H3z",
    "folder-output": "M3 7h7l2 3h9v9H3z M12 14h6M15 11l3 3-3 3",
    "save": "M5 4h12l2 2v14H5z M8 4v6h8M8 20v-6h8v6",
    "refresh": "M19 8v5h-5M5 16v-5h5M18 13a6 6 0 0 0-10-5M6 11a6 6 0 0 0 10 5",
    "search": "M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13ZM16 16l5 5",
    "filter": "M4 5h16l-6 7v6l-4 2v-8z",
    "sort": "M8 5v14M5 8l3-3 3 3M16 19V5M13 16l3 3 3-3",
    "sort-asc": "M11 5H4M11 12H4M18 19H4M15 5v12M12 14l3 3 3-3",
    "sort-desc": "M18 5H4M14 12H4M10 19H4M15 19V7M12 10l3-3 3 3",
    "play": "M8 5v14l11-7z",
    "pause": "M7 5h4v14H7z M14 5h4v14h-4z",
    "stop": "M7 7h10v10H7z",
    "retry": "M19 8v5h-5M5 16v-5h5M18 13a6 6 0 0 0-10-5M6 11a6 6 0 0 0 10 5",
    "skip": "M6 6l7 6-7 6z M14 6h4v12h-4z",
    "reset": "M7 7h10v10H7z M9 4h6M9 20h6",
    "dry-run": "M8 5v14l10-7z M4 4v16",
    "preflight": "M9 12l2 2 4-5 M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20",
    "favorite-outline": "M12 4l2.4 5 5.6.8-4 3.9.9 5.5L12 16l-5 2.7.9-5.5-4-3.9 5.6-.8z",
    "favorite-filled": "M12 4l2.4 5 5.6.8-4 3.9.9 5.5L12 16l-5 2.7.9-5.5-4-3.9 5.6-.8z",
    "voice": "M7 10a5 5 0 0 1 10 0v2a5 5 0 0 1-10 0z M12 17v4M8 21h8",
    "voices": "M8 10a4 4 0 0 1 8 0v2a4 4 0 0 1-8 0z M12 16v4M9 20h6 M4 9a3 3 0 0 1 3-3 M20 9a3 3 0 0 0-3-3",
    "waveform": "M4 12h3l2-7 4 14 3-10 2 3h2",
    "provider/account": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21a8 8 0 0 1 16 0",
    "accounts": "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2 20a6 6 0 0 1 12 0M17 8h5M17 12h5M17 16h5",
    "key": "M15 7a4 4 0 1 0-2.5 3.7L20 18v2h-2l-2-2h-2v-2l-2.7-2.7",
    "replace-key": "M15 7a4 4 0 1 0-2.5 3.7L20 18v2h-2l-2-2h-2v-2l-2.7-2.7 M4 20h6M7 17v6",
    "temporary-key": "M15 7a4 4 0 1 0-2.5 3.7L20 18v2h-2l-2-2h-2v-2 M4 5v5h5",
    "verify": "M20 6 9 17l-5-5 M4 21h16",
    "plug": "M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0z M12 16v5",
    "quota": "M4 18V9a8 8 0 0 1 16 0v9 M8 18v-5M12 18V8M16 18v-8",
    "model": "M5 5h14v14H5z M9 9h6v6H9z M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3",
    "language": "M4 5h10M9 5c-.5 5-2 8-5 11M6 10h8M11 10c1 3 3 5 5 6M15 20l4-10 4 10M16.5 17h5",
    "dictionary": "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z M8 4v13a3 3 0 0 0 3 3",
    "dictionary-add": "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z M8 4v13a3 3 0 0 0 3 3 M12 9v6M9 12h6",
    "import-pls": "M6 3h9l4 4v14H6z M14 3v5h5 M12 10v7M9 14l3 3 3-3",
    "sync": "M19 8v5h-5M5 16v-5h5M18 13a6 6 0 0 0-10-5M6 11a6 6 0 0 0 10 5",
    "pronunciation-test": "M4 12h3l2-7 4 14 3-10 2 3h2 M19 5l3 3-3 3",
    "settings": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1",
    "project": "M4 6h6l2 3h8v11H4z",
    "queue": "M5 7h14M5 12h14M5 17h14",
    "report": "M6 4h9l3 3v13H6z M14 4v4h4M9 12h6M9 16h6",
    "notification": "M7 18h10M9 18a3 3 0 0 0 6 0M8 9a4 4 0 0 1 8 0v4l2 3H6l2-3z",
    "activity": "M4 12h4l2-6 4 12 2-6h4",
    "text": "M5 4h14v16H5z M8 8h8M8 12h8M8 16h5",
    "history": "M4 12a8 8 0 1 0 3-6M4 4v6h6M12 8v5l4 2",
    "health": "M12 21s-8-4.8-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 6.2-8 11-8 11z",
    "warning": "M12 4 22 20H2z M12 9v5M12 17h.01",
    "error": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM8 8l8 8M16 8l-8 8",
    "success": "M20 6 9 17l-5-5",
    "info": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM12 10v7M12 7h.01",
    "more": "M5 12h.01M12 12h.01M19 12h.01",
    "rename": "M4 17.5V20h2.5L18 8.5 15.5 6 4 17.5Z M14.5 7 17 9.5 M4 4h9",
    "toggle": "M8 12a4 4 0 1 0 0 .01M8 6h8a6 6 0 0 1 0 12H8",
    "clear": "M5 7h14M9 7V5h6v2M8 10v9h8v-9 M10 12l4 4M14 12l-4 4",
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

ACTION_ICONS: dict[str, str] = {
    "project.new": "new",
    "project.open": "open",
    "project.save": "save",
    "project.add_sources": "add",
    "project.add_text_source": "text",
    "project.output_folder": "folder-output",
    "provider.accounts": "accounts",
    "provider.test_connection": "plug",
    "provider.refresh_account": "refresh",
    "provider.refresh_models": "model",
    "provider.browse_voices": "voices",
    "provider.set_active_profile": "verify",
    "provider.add_profile": "add",
    "provider.rename_profile": "rename",
    "provider.replace_key": "replace-key",
    "provider.delete_profile": "delete",
    "provider.toggle_enabled": "toggle",
    "provider.move_up": "chevron-up",
    "provider.move_down": "chevron-down",
    "provider.live_verification": "verify",
    "provider.test_all": "activity",
    "provider.clear_exhausted": "clear",
    "provider.temporary_key": "temporary-key",
    "provider.copy_summary": "copy",
    "generation.start": "play",
    "generation.pause": "pause",
    "generation.stop": "stop",
    "generation.retry": "retry",
    "generation.skip": "skip",
    "generation.reset": "reset",
    "generation.dry_run": "dry-run",
    "generation.preflight": "preflight",
    "pronunciation.dictionary": "dictionary",
    "pronunciation.add_rule": "dictionary-add",
    "pronunciation.import_pls": "import-pls",
    "pronunciation.sync": "sync",
    "pronunciation.test": "pronunciation-test",
    "pronunciation.toggle_dictionary": "toggle",
    "general.settings": "settings",
    "general.edit": "edit",
    "general.remove": "remove",
    "general.clear": "clear",
    "general.refresh": "refresh",
    "general.copy": "copy",
    "general.more": "more",
    "general.warning": "warning",
    "general.error": "error",
    "general.success": "success",
    "general.info": "info",
    "general.account": "provider/account",
    "general.key": "key",
    "general.quota": "quota",
}


_ICON_METADATA: dict[int, tuple[str, int, str | None]] = {}
_ICON_CACHE: dict[tuple[str, int, str, bool, float], QIcon] = {}


def _device_pixel_ratio() -> float:
    app = QApplication.instance()
    if app is None:
        return 1.0
    ratios = [float(screen.devicePixelRatio()) for screen in app.screens()]
    return max([1.0, *ratios])


def _render_icon(name: str, *, size: int, color: str | None = None) -> QIcon:
    app = QApplication.instance()
    if app is None:
        return QIcon()
    resolved = name if name in ICON_REGISTRY else ALIASES.get(name, "project")
    path = ICON_REGISTRY.get(resolved, ICON_REGISTRY["project"])
    stroke = color or app.palette().buttonText().color().name()
    device_ratio = _device_pixel_ratio()
    cache_key = (resolved, int(size), stroke.casefold(), color is not None, device_ratio)
    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        result = QIcon(cached)
        _ICON_METADATA[result.cacheKey()] = (resolved, size, color)
        return result

    fill = stroke if resolved == "favorite-filled" else "none"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    physical_size = max(int(size), int(round(size * device_ratio)))
    pixmap = QPixmap(physical_size, physical_size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(device_ratio)
    result = QIcon(pixmap)
    _ICON_CACHE[cache_key] = QIcon(result)
    _ICON_METADATA[result.cacheKey()] = (resolved, size, color)
    return result


def icon(name: str, *, size: int = 20, color: str | None = None) -> QIcon:
    """Return a monochrome icon using the active application palette.

    Icons are tagged with their source metadata so ``refresh_icons`` can
    recolor already-created actions and buttons after a runtime theme switch.
    """

    return _render_icon(name, size=size, color=color)


def action_icon(action: str, *, size: int = 20, color: str | None = None) -> QIcon:
    return icon(ACTION_ICONS.get(action, action), size=size, color=color)


def _refresh_owner(owner: object) -> bool:
    getter = getattr(owner, "icon", None)
    setter = getattr(owner, "setIcon", None)
    if not callable(getter) or not callable(setter):
        return False
    try:
        current = getter()
    except RuntimeError:
        return False
    if current is None or current.isNull():
        return False
    metadata = _ICON_METADATA.get(current.cacheKey())
    if metadata is None:
        return False
    name, size, color = metadata
    if color is not None:
        return False
    setter(_render_icon(name, size=size, color=None))
    return True


def _actions_for_widget(widget: QWidget) -> tuple[QAction, ...]:
    """Return actions without assuming ``QWidget.actions`` is callable."""

    actions_attr = getattr(widget, "actions", None)
    if callable(actions_attr):
        try:
            return tuple(actions_attr())
        except (RuntimeError, TypeError):
            return ()
    if isinstance(actions_attr, (list, tuple, set)):
        return tuple(action for action in actions_attr if isinstance(action, QAction))
    return ()


def refresh_icons(root: QObject | None = None) -> int:
    """Recolor registered icons inside one live object tree.

    Runtime theme changes normally pass the active ``MainWindow`` as ``root``.
    This avoids rescanning and rerendering every stale widget retained by a
    long-lived ``QApplication`` (notably the shared offscreen test session).
    Calling without a root remains supported for standalone controls.
    """

    app = QApplication.instance()
    if app is None:
        return 0

    roots: tuple[QObject, ...]
    if root is not None:
        roots = (root,)
    else:
        roots = tuple(app.topLevelWidgets())

    seen: set[int] = set()
    refreshed = 0

    def refresh(owner: object) -> None:
        nonlocal refreshed
        identity = id(owner)
        if identity in seen:
            return
        seen.add(identity)
        if _refresh_owner(owner):
            refreshed += 1

    for scope in roots:
        if isinstance(scope, QAbstractButton):
            refresh(scope)
        if isinstance(scope, QAction):
            refresh(scope)

        widgets: list[QWidget] = []
        if isinstance(scope, QWidget):
            widgets.append(scope)
        widgets.extend(scope.findChildren(QWidget))
        for widget in widgets:
            if isinstance(widget, QAbstractButton):
                refresh(widget)
            for action in _actions_for_widget(widget):
                refresh(action)

        for action in scope.findChildren(QAction):
            refresh(action)

    return refreshed


def required_icon_names() -> set[str]:
    return set(ICON_REGISTRY)
