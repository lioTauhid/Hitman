"""Stroke icons (24x24 SVG paths from the design) rendered to QIcon / QPixmap in any color."""

from __future__ import annotations

import atexit
import hashlib
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "search": "M4 11a7 7 0 1 0 14 0a7 7 0 1 0-14 0M21 21l-4.35-4.35",
    "sun": "M8 12a4 4 0 1 0 8 0a4 4 0 1 0-8 0M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41",
    "moon": "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z",
    "sliders": "M3 7h2.5M10.5 7H21M3 17h10.5M18.5 17H21M5.5 7a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M13.5 17a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0",
    "plus": "M12 5v14M5 12h14",
    "x": "M18 6 6 18M6 6l12 12",
    "chevR": "M9 6l6 6-6 6",
    "chevD": "M6 9l6 6 6-6",
    "folder": "M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h7.5A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z",
    "layers": "M12 2.5 21.5 7.5 12 12.5 2.5 7.5zM2.5 12l9.5 5 9.5-5M2.5 16.5l9.5 5 9.5-5",
    "import": "M12 3v12M7 10l5 5 5-5M4 20h16",
    "export": "M12 15V3M7 8l5-5 5 5M4 20h16",
    "more": "M5 12h.01M12 12h.01M19 12h.01",
    "braces": "M8 3H7a2 2 0 0 0-2 2v4a2 2 0 0 1-2 2 2 2 0 0 1 2 2v4a2 2 0 0 0 2 2h1M16 3h1a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2 2 2 0 0 0-2 2v4a2 2 0 0 1-2 2h-1",
    "clock": "M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5M3.5 3.5v5h5M12 7.5V12l3 2",
    "check": "M20 6 9 17l-5-5",
    "xCircle": "M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M15 9l-6 6M9 9l6 6",
    "eye": "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
    "copy": "M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1",
    "save": "M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM7 3v5h8V3M7 21v-7h10v7",
    "code": "M16 18l6-6-6-6M8 6l-6 6 6 6",
    "trash": "M3 6h18M8 6V4h8v2M5.5 6l1 14h11l1-14M10 10.5v6M14 10.5v6",
    "send": "M21.5 2.5 10.5 13.5M21.5 2.5 14.5 21.5l-4-8-8-4z",
    "rows": "M3 4h18v16H3zM3 12h18",
    "cols": "M3 4h18v16H3zM12 4v16",
    "file": "M14 3H6.5A2.5 2.5 0 0 0 4 5.5v13A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V9zM14 3v6h6",
    "lock": "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    "upload": "M12 13v8M8 17l4-4 4 4M20 16.6A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25",
    "keyboard": "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10",
    "info": "M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M12 11v5M12 8h.01",
    "edit": "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
    "up": "M6 15l6-6 6 6",
    "down": "M6 9l6 6 6-6",
    "collapse": "M7 4l5 5 5-5M7 20l5-5 5 5",
    "expand": "M7 9l5-5 5 5M7 15l5 5 5-5",
}

BOLT = "M13.5 2 5 13.6h6.1L10 22l9-12.1h-6.3L13.5 2z"


def svg(name: str, color: str, stroke: float = 1.8, filled: bool = False) -> str:
    path = BOLT if name == "bolt" else PATHS[name]
    if filled or name == "bolt":
        body = f'<path d="{path}" fill="{color}"/>'
    else:
        body = (f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{stroke}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


def _color_arg(color: QColor | str) -> str:
    c = QColor(color)
    return c.name(QColor.NameFormat.HexRgb) if c.alpha() == 255 else f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.3f})"


@lru_cache(maxsize=1024)
def _pixmap(name: str, color: str, size: int, stroke: float, scale: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg(name, color, stroke).encode()))
    pixmap = QPixmap(round(size * scale), round(size * scale))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pixmap.width(), pixmap.height()))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def pixmap(name: str, color: QColor | str, size: int = 16, stroke: float = 1.8, scale: float = 2.0) -> QPixmap:
    return _pixmap(name, _color_arg(color), size, stroke, scale)


def icon(name: str, color: QColor | str, size: int = 16, stroke: float = 1.8) -> QIcon:
    result = QIcon()
    for scale in (1.0, 2.0, 3.0):
        result.addPixmap(pixmap(name, color, size, stroke, scale))
    return result


def paint(painter: QPainter, name: str, color: QColor | str, rect: QRectF, stroke: float = 1.8) -> None:
    """Draw an icon directly (used by custom-painted widgets)."""
    size = round(rect.width())
    scale = painter.device().devicePixelRatioF() if painter.device() else 2.0
    painter.drawPixmap(rect.toRect(), pixmap(name, color, size, stroke, max(scale, 1.0)))


_ASSET_DIR = Path(tempfile.mkdtemp(prefix="hitman-ui-"))
atexit.register(shutil.rmtree, _ASSET_DIR, True)


def svg_file(markup: str) -> str:
    """Write SVG markup to a cached temp file and return a forward-slash path for style sheets."""
    digest = hashlib.sha1(markup.encode()).hexdigest()[:16]
    path = _ASSET_DIR / f"{digest}.svg"
    if not path.exists():
        path.write_text(markup, encoding="utf-8")
    return path.as_posix()
