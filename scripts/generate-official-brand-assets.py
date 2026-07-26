from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> None:
    QApplication.instance() or QApplication([])
    official = Path("app/resources/brand/official")
    master = official / "S-Logo.svg"
    if not master.exists():
        raise SystemExit(f"Official logo missing: {master}")
    data = master.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    renderer = QSvgRenderer(str(master))
    if not renderer.isValid():
        raise SystemExit(f"Official logo is not a valid SVG: {master}")
    sizes = (16, 24, 32, 48, 64, 128, 256, 512)
    pngs: list[str] = []
    icon = QIcon()
    for size in sizes:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        path = official / f"S-Logo-{size}.png"
        if not pixmap.save(str(path)):
            raise SystemExit(f"Could not write {path}")
        icon.addFile(str(path))
        pngs.append(path.name)
    ico_path = official / "S-Logo.ico"
    if not icon.pixmap(256, 256).save(str(ico_path)):
        raise SystemExit(f"Could not write {ico_path}")
    manifest = {
        "schema_version": 1,
        "master": "S-Logo.svg",
        "sha256": sha,
        "derived_png": pngs,
        "derived_ico": ico_path.name,
        "source_path": "D:/Projects/S Leraning Project/Design elements/S-Logo.svg",
    }
    (official / "brand-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(sha)


if __name__ == "__main__":
    main()
