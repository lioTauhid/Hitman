"""Left rail switching the sidebar between Collections, Environments and History."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QAbstractButton, QFrame, QWidget

from hitman.ui import icons
from hitman.ui.fonts import ui_font
from hitman.ui.theme import manager, theme
from hitman.ui.widgets.common import IconButton, vbox

SECTIONS = [
    ("collections", "Collections", "Collections", "layers"),
    ("environments", "Environments", "Envs", "braces"),
    ("history", "History", "History", "clock"),
]


class _RailButton(QAbstractButton):
    def __init__(self, key: str, label: str, short: str, icon: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key, self._short, self._icon = key, short, icon
        self.setCheckable(True)
        self.setFixedSize(58, 50)  # wider than its 48px surface so long labels aren't clipped
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        self.setAccessibleName(label)
        manager().changed.connect(self.update)

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
        if on or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("surface3"))
            painter.drawRoundedRect(QRectF(5, 0, 48, self.height()), 10, 10)
        color = t.c("fg") if on else t.c("fg3")
        icons.paint(painter, self._icon, color, QRectF(20, 9, 18, 18))
        painter.setFont(ui_font(10, 500))
        painter.setPen(color)
        painter.drawText(QRectF(0, 31, self.width(), 14), Qt.AlignmentFlag.AlignHCenter, self._short)


class Rail(QFrame):
    section_clicked = Signal(str)
    open_settings = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Rail")
        self.setFixedWidth(60)
        layout = vbox(self, (1, 10, 1, 10), 4)
        self._buttons: dict[str, _RailButton] = {}
        for key, label, short, icon in SECTIONS:
            btn = _RailButton(key, label, short, icon)
            btn.clicked.connect(lambda _c=False, k=key: self.section_clicked.emit(k))
            self._buttons[key] = btn
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        settings = IconButton("sliders", "Settings", size=(48, 44), icon_size=18, role="fg3", radius=10)
        settings.clicked.connect(self.open_settings)
        layout.addWidget(settings, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_state(self, section: str, sidebar_visible: bool) -> None:
        for key, btn in self._buttons.items():
            btn.setChecked(sidebar_visible and key == section)
