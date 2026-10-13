"""Popover menus and floating panels anchored to a widget."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QGuiApplication, QKeyEvent, QPainter
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QWidget

from hitman.ui import icons
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import set_cls, theme
from hitman.ui.widgets.common import separator, vbox


class FloatingPanel(QFrame):
    """Top-level popup with a styled inner frame; closes when clicking outside."""

    def __init__(self, parent: QWidget | None = None, object_name: str = "Popover", margins=(4, 4, 4, 4)):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        outer = vbox(self)
        self.frame = QFrame(self)
        self.frame.setObjectName(object_name)
        outer.addWidget(self.frame)
        self.body = vbox(self.frame, margins, 0)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def show_at(self, anchor: QWidget | QRect, *, align: str = "left", offset: int = 4,
                width: int | None = None) -> None:
        """Show below `anchor` (a widget or a global rect), flipping above if there's no room."""
        rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size()) if isinstance(anchor, QWidget) else anchor
        if width:
            self.setFixedWidth(width)
        self.adjustSize()
        size = self.sizeHint()
        x = rect.left() if align == "left" else rect.right() + 1 - size.width()
        y = rect.bottom() + 1 + offset
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        bounds = screen.availableGeometry()
        if x + size.width() > bounds.right() - 8:
            x = bounds.right() - 8 - size.width()
        if y + size.height() > bounds.bottom() - 8:
            y = rect.top() - offset - size.height()
        self.move(max(bounds.left() + 8, x), max(bounds.top() + 8, y))
        self.show()


class _MenuItem(QAbstractButton):
    def __init__(self, text: str, *, checked: bool, dot: str | None, role: str, mono: bool, kbd: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._text, self._checked, self._dot, self._role, self._kbd = text, checked, dot, role, kbd
        self.setFont(mono_font(12.5, 600) if mono else ui_font(12.5))
        self.setFixedHeight(30)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = 8 + 14 + 10 + QFontMetrics(self.font()).horizontalAdvance(self._text) + 10
        if self._kbd:
            width += 16 + QFontMetrics(mono_font(10.5)).horizontalAdvance(self._kbd)
        return QSize(width, 30)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setFocus()
        super().enterEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.hasFocus() or self.isDown():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("surface3"))
            painter.drawRoundedRect(QRectF(self.rect()), 6, 6)
        mid = self.height() / 2
        if self._checked:
            icons.paint(painter, "check", t.c("accent_text"), QRectF(8.5, mid - 6.5, 13, 13), 2.4)
        elif self._dot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.env_color(self._dot))
            painter.drawEllipse(QRectF(11, mid - 4, 8, 8))
        painter.setFont(self.font())
        painter.setPen(t.c(self._role))
        text_rect = QRectF(32, 0, self.width() - 42, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        if self._kbd:
            painter.setFont(mono_font(10.5))
            painter.setPen(t.c("fg3"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._kbd)


class PopoverMenu(FloatingPanel):
    """The design's menu: items with optional check, colored dot, mono/colored text and a shortcut hint."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list[_MenuItem] = []

    def add_item(self, text: str, callback: Callable[[], None] | None = None, *, checked: bool = False,
                 dot: str | None = None, role: str = "fg", mono: bool = False, kbd: str = "") -> None:
        item = _MenuItem(text, checked=checked, dot=dot, role=role, mono=mono, kbd=kbd, parent=self.frame)
        item.clicked.connect(lambda: self._activate(callback))
        self._items.append(item)
        self.body.addWidget(item)

    def add_header(self, text: str) -> None:
        header = QLabel(text.upper())
        set_cls(header, "caps")
        font = ui_font(10.5, 600)
        font.setLetterSpacing(font.SpacingType.AbsoluteSpacing, 0.6)
        header.setFont(font)
        header.setContentsMargins(10, 6, 10, 4)
        self.body.addWidget(header)

    def add_separator(self) -> None:
        holder = QWidget(self.frame)
        vbox(holder, (2, 4, 2, 4)).addWidget(separator(vertical=False))
        self.body.addWidget(holder)

    def _activate(self, callback: Callable[[], None] | None) -> None:
        self.close()
        if callback:
            QTimer.singleShot(0, callback)

    def show_at(self, anchor: QWidget | QRect, **kwargs) -> None:
        super().show_at(anchor, **kwargs)
        target = next((i for i in self._items if i._checked), self._items[0] if self._items else None)
        if target:
            target.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._items:
            current = next((i for i, item in enumerate(self._items) if item.hasFocus()), -1)
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self._items[(current + step) % len(self._items)].setFocus()
            return
        super().keyPressEvent(event)


def chip_label(text: str) -> QLabel:
    return set_cls(QLabel(text), "chip")
