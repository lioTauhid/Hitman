"""Small building blocks used throughout the UI."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout,
                               QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from hitman.ui import icons
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import manager, set_cls, theme

# ------------------------------------------------------------------ layouts


def hbox(parent: QWidget | None = None, margins=(0, 0, 0, 0), spacing: int = 0) -> QHBoxLayout:
    layout = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def vbox(parent: QWidget | None = None, margins=(0, 0, 0, 0), spacing: int = 0) -> QVBoxLayout:
    layout = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def label(text: str = "", cls: str | None = None, *, wrap: bool = False, selectable: bool = False) -> QLabel:
    widget = QLabel(text)
    if cls:
        set_cls(widget, cls)
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text: str, cls: str | None = None, *, icon: str | None = None, icon_role: str = "fg2",
           icon_size: int = 15, height: int | None = None, on_click: Callable | None = None) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setAutoDefault(False)
    if cls:
        set_cls(widget, cls)
    if icon:
        manager().bind_icon(widget, icon, icon_role, icon_size)
    if height:
        widget.setFixedHeight(height)
    if on_click:
        widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def separator(vertical: bool = True) -> QFrame:
    line = QFrame()
    set_cls(line, "separator-v" if vertical else "hline")
    if not vertical:
        line.setFixedHeight(1)
    return line


# ---------------------------------------------------------------- painting


class RoleLabel(QLabel):
    """A label whose color comes from a theme token (or a callable returning a QColor)."""

    def __init__(self, text: str = "", role: str | Callable[[], QColor] = "fg", *, px: float = 12.5,
                 weight: int = 400, mono: bool = False, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._role = role
        self.setFont(mono_font(px, weight) if mono else ui_font(px, weight))
        manager().changed.connect(self._apply)
        self._apply()

    def set_role(self, role: str | Callable[[], QColor]) -> None:
        self._role = role
        self._apply()

    def _apply(self) -> None:
        color = self._role() if callable(self._role) else theme().c(self._role)
        self.setStyleSheet(f"color: {color.name(QColor.NameFormat.HexArgb)}; background: transparent;")


class ElidedLabel(QWidget):
    """Single-line text that elides with an ellipsis instead of growing."""

    def __init__(self, text: str = "", role: str = "fg", *, px: float = 12.5, weight: int = 400,
                 mono: bool = False, elide=Qt.TextElideMode.ElideRight, parent: QWidget | None = None):
        super().__init__(parent)
        self._text, self._role, self._elide = text, role, elide
        self.setFont(mono_font(px, weight) if mono else ui_font(px, weight))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(10)
        manager().changed.connect(self.update)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def text(self) -> str:
        return self._text

    def set_role(self, role: str) -> None:
        self._role = role
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._text) + 2, fm.height())

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(theme().c(self._role))
        fm = painter.fontMetrics()
        text = fm.elidedText(self._text, self._elide, self.width())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class IconButton(QAbstractButton):
    """Icon-only button with the design's hover/pressed surface."""

    def __init__(self, icon: str, tooltip: str = "", *, size: tuple[int, int] = (28, 28), icon_size: int = 16,
                 role: str = "fg2", stroke: float = 1.8, radius: float = 7, bordered: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._icon, self._role, self._icon_size, self._stroke = icon, role, icon_size, stroke
        self._radius, self._bordered = radius, bordered
        self.setFixedSize(*size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
        manager().changed.connect(self.update)

    def set_icon(self, name: str) -> None:
        self._icon = name
        self.update()

    def set_role(self, role: str) -> None:
        self._role = role
        self.update()

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
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        active = self.isEnabled() and (self.underMouse() or self.isDown() or self.isChecked())
        if self._bordered:
            painter.setPen(QPen(t.c("line"), 1))
            painter.setBrush(t.c("surface3") if active else t.c("surface"))
            painter.drawRoundedRect(rect, self._radius, self._radius)
        elif active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("surface3"))
            painter.drawRoundedRect(rect, self._radius, self._radius)
        color = t.c(self._role)
        if not self.isEnabled():
            color.setAlphaF(0.4)
        s = self._icon_size
        target = QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)
        icons.paint(painter, self._icon, color, target, self._stroke)


class ColorDot(QWidget):
    def __init__(self, token: str = "fg3", size: int = 8, parent: QWidget | None = None):
        super().__init__(parent)
        self._token = token
        self.setFixedSize(size, size)
        manager().changed.connect(self.update)

    def set_token(self, token: str) -> None:
        self._token = token
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme().env_color(self._token))
        painter.drawEllipse(QRectF(self.rect()))


class Spinner(QWidget):
    """Rotating arc. `ring=True` draws the faint full circle behind it."""

    def __init__(self, size: int = 28, *, ring: bool = True, role: str = "accent_text", width: float = 2.0,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._angle, self._ring, self._role, self._width = 0, ring, role, width
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._angle = (self._angle + 7) % 360
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self._width / 2 + self.width() * 0.08
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        if self._ring:
            painter.setPen(QPen(t.c("line_strong"), self._width))
            painter.drawEllipse(rect)
        pen = QPen(t.c(self._role), self._width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = 90 if self._ring else 270
        painter.drawArc(rect, int(-self._angle * 16), int(-span * 16))


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, *, small: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(*((30, 18) if small else (34, 20)))
        manager().changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(t.c("accent") if self.isChecked() else t.c("line_strong"))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        knob = rect.height() - 4
        x = rect.width() - knob - 2 if self.isChecked() else 2
        painter.setBrush(t.c("on_accent") if self.isChecked() else t.c("fg3"))
        painter.drawEllipse(QRectF(x, 2, knob, knob))


class SegmentedControl(QFrame):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str | None = None, *, large: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        set_cls(self, "segmented-lg" if large else "segmented")
        layout = hbox(self, (3, 3, 3, 3) if large else (2, 2, 2, 2), 0)
        self._group = QButtonGroup(self)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            btn = button(text, "segment", height=26 if large else 24)
            btn.setCheckable(True)
            if large:
                btn.setStyleSheet("padding: 0 12px;")
            self._group.addButton(btn)
            self._buttons[key] = btn
            layout.addWidget(btn)
            btn.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
        self.set_value(value or options[0][0])

    def set_value(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def value(self) -> str:
        return next((k for k, b in self._buttons.items() if b.isChecked()), "")


class SearchField(QFrame):
    """A rounded field with a leading search icon."""

    def __init__(self, placeholder: str, *, height: int = 30, strong: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        set_cls(self, "field-strong" if strong else "field")
        self.setFixedHeight(height)
        layout = hbox(self, (9, 0, 6, 0), 7)
        icon = QLabel()
        manager().bind_icon(icon, "search", "fg3", 14)
        self.edit = QLineEdit()
        set_cls(self.edit, "bare")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setAccessibleName(placeholder)
        self.edit.setStyleSheet("padding: 0;")
        self.edit.setClearButtonEnabled(False)
        layout.addWidget(icon)
        layout.addWidget(self.edit, 1)

    def text(self) -> str:
        return self.edit.text()


class SelectButton(QPushButton):
    """A button that looks like a dropdown: [dot] text  ⌄. Clicking calls `on_open(self)`."""

    def __init__(self, text: str = "", *, dot: str | None = None, mono: bool = False, px: float = 12.5,
                 weight: int = 400, role: str | Callable[[], QColor] = "fg", height: int = 34,
                 margins=(10, 0, 8, 0), on_open: Callable[[QWidget], None] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        set_cls(self, "select")
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(height)
        layout = hbox(self, margins, 8)
        self.dot = ColorDot(dot or "fg3") if dot is not None else None
        if self.dot:
            layout.addWidget(self.dot)
        self.text_label = RoleLabel(text, role, px=px, weight=weight, mono=mono)
        layout.addWidget(self.text_label, 1)
        chevron = QLabel()
        manager().bind_icon(chevron, "chevD", "fg3", 13, 2)
        layout.addWidget(chevron)
        for child in (self.text_label, chevron, self.dot):
            if child:
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if on_open:
            self.clicked.connect(lambda _c=False: on_open(self))

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)
        self.setAccessibleName(text)

    def set_role(self, role: str | Callable[[], QColor]) -> None:
        self.text_label.set_role(role)

    def set_dot(self, token: str) -> None:
        if self.dot:
            self.dot.set_token(token)


class CheckRow(QWidget):
    """Checkbox with a title and a muted description; clicking anywhere toggles it."""

    def __init__(self, title: str, description: str = "", checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = hbox(self, spacing=9)
        self.check = QCheckBox()
        self.check.setChecked(checked)
        self.check.setAccessibleName(title)
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        text = vbox(spacing=1)
        text.addWidget(RoleLabel(title, "fg", px=12.5))
        if description:
            text.addWidget(RoleLabel(description, "fg3", px=11.5))
        layout.addLayout(text, 1)
        self.toggled = self.check.toggled

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.check.toggle()

    def isChecked(self) -> bool:  # noqa: N802
        return self.check.isChecked()


class CardButton(QPushButton):
    """A checkable button laid out with child widgets; sized from its layout rather than its text."""

    def __init__(self, cls: str, accessible_name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        set_cls(self, cls)
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(accessible_name)

    def finish(self) -> CardButton:
        """Call after adding children: lets clicks on child labels reach the button."""
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return self

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.layout().totalSizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.layout().totalMinimumSize() if self.layout() else super().minimumSizeHint()
