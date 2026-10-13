"""Bundled fonts (Geist / Geist Mono, SIL OFL 1.1) and size helpers.

Sizes in the design are pixels, often fractional (12.5px). Qt style sheets only accept
whole pixels, so everything is expressed in points converted from pixels at the
screen's logical DPI, which keeps fractional sizes intact.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

from hitman.paths import FONTS_DIR

UI_FAMILY = "Geist"
MONO_FAMILY = "Geist Mono"
_FALLBACK_UI = ["Geist", ".AppleSystemUIFont", "Segoe UI", "Inter", "Helvetica Neue", "Arial"]
_FALLBACK_MONO = ["Geist Mono", "SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "monospace"]


def load_fonts() -> None:
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def px_to_pt(px: float) -> float:
    screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInchY() if screen else 72.0
    return px * 72.0 / (dpi or 72.0)


def _font(families: list[str], px: float, weight: int) -> QFont:
    font = QFont()
    font.setFamilies(families)
    font.setPointSizeF(px_to_pt(px))
    font.setWeight(QFont.Weight(weight))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def ui_font(px: float = 13, weight: int = 400) -> QFont:
    return _font(_FALLBACK_UI, px, weight)


def mono_font(px: float = 12.5, weight: int = 400) -> QFont:
    font = _font(_FALLBACK_MONO, px, weight)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font
