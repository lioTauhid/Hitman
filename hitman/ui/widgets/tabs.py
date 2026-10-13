"""Underlined section tabs (Params / Authorization / Headers / Body, etc.)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QWidget

from hitman.ui import icons
from hitman.ui.fonts import ui_font
from hitman.ui.theme import manager, theme
from hitman.ui.widgets.common import hbox


class UnderlineTab(QAbstractButton):
    def __init__(self, key: str, text: str, *, icon: str | None = None, count_style: str = "pill",
                 height: int = 36, padding: int = 9, parent: QWidget | None = None):
        super().__init__(parent)
        self.key, self._text, self._icon = key, text, icon
        self._count: str = ""
        self._dot = False
        self._count_style = count_style
        self._padding = padding
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(height)
        self.setFont(ui_font(12.5, 500))
        self.setAccessibleName(text)
        manager().changed.connect(self.update)

    def set_count(self, count: int | str | None) -> None:
        self._count = "" if count in (None, 0, "") else str(count)
        self.updateGeometry()
        self.update()

    def set_dot(self, on: bool) -> None:
        self._dot = on
        self.updateGeometry()
        self.update()

    def _badge_width(self) -> int:
        if not self._count:
            return 0
        fm = QFontMetrics(ui_font(10.5 if self._count_style == "pill" else 11))
        width = fm.horizontalAdvance(self._count)
        return max(18, width + 10) if self._count_style == "pill" else width

    def sizeHint(self) -> QSize:  # noqa: N802
        width = QFontMetrics(self.font()).horizontalAdvance(self._text) + self._padding * 2
        if self._icon:
            width += 14 + 7
        if self._count:
            width += 6 + self._badge_width()
        if self._dot:
            width += 6 + 6
        return QSize(width, self.height())

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        color = t.c("fg") if on or self.underMouse() else t.c("fg3")
        x = float(self._padding)
        mid = self.height() / 2
        if self._icon:
            icons.paint(painter, self._icon, color, QRectF(x, mid - 7, 14, 14))
            x += 14 + 7
        painter.setFont(self.font())
        painter.setPen(color)
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(self._text)
        painter.drawText(QRectF(x, 0, text_w + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, self._text)
        x += text_w + 6
        if self._count:
            bw = self._badge_width()
            if self._count_style == "pill":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(t.c("surface3"))
                painter.drawRoundedRect(QRectF(x, mid - 8, bw, 16), 8, 8)
                painter.setFont(ui_font(10.5))
                painter.setPen(t.c("fg2"))
                painter.drawText(QRectF(x, mid - 8, bw, 16), Qt.AlignmentFlag.AlignCenter, self._count)
            else:
                painter.setFont(ui_font(11))
                painter.setPen(t.c("fg3"))
                painter.drawText(QRectF(x, 0, bw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, self._count)
            x += bw + 6
        if self._dot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("accent_text"))
            painter.drawEllipse(QRectF(x, mid - 3, 6, 6))
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("accent_text"))
            painter.drawRoundedRect(QRectF(8, self.height() - 2, self.width() - 16, 2), 1, 1)


class UnderlineTabs(QWidget):
    changed = Signal(str)

    def __init__(self, tabs: list[tuple], *, height: int = 36, count_style: str = "pill",
                 margins=(10, 0, 10, 0), spacing: int = 2, parent: QWidget | None = None):
        super().__init__(parent)
        layout = hbox(self, margins, spacing)
        self._group = QButtonGroup(self)
        self._tabs: dict[str, UnderlineTab] = {}
        for spec in tabs:
            key, text = spec[0], spec[1]
            tab = UnderlineTab(key, text, icon=spec[2] if len(spec) > 2 else None,
                               count_style=count_style, height=height)
            self._group.addButton(tab)
            self._tabs[key] = tab
            layout.addWidget(tab)
            tab.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
        layout.addStretch(1)
        self.set_current(tabs[0][0])

    def set_current(self, key: str) -> None:
        if key in self._tabs:
            self._tabs[key].setChecked(True)

    def current(self) -> str:
        return next((k for k, t in self._tabs.items() if t.isChecked()), "")

    def set_count(self, key: str, count) -> None:
        self._tabs[key].set_count(count)

    def set_dot(self, key: str, on: bool) -> None:
        self._tabs[key].set_dot(on)
