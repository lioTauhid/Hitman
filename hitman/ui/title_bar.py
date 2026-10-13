"""Top bar: logo, app name, theme toggle, settings and (on Windows/Linux) window controls."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QSizePolicy, QWidget

from hitman import APP_NAME
from hitman.ui import icons
from hitman.ui.theme import ACCENT, ON_ACCENT, manager, theme
from hitman.ui.widgets.common import IconButton, hbox

TRAFFIC_LIGHTS_INSET = 72  # room for macOS window buttons


class _WindowButton(QAbstractButton):
    def __init__(self, kind: str, tooltip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedWidth(46)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        hover = self.underMouse()
        if hover:
            painter.fillRect(self.rect(), QColor("#D9363E") if self.kind == "close" else t.c("surface3"))
        color = QColor("#FFFFFF") if hover and self.kind == "close" else t.c("fg2")
        painter.setPen(QPen(color, 1.1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        if self.kind == "min":
            painter.drawLine(QPointF(cx - 4.5, cy), QPointF(cx + 4.5, cy))
        elif self.kind == "max":
            maximized = self.window().isMaximized()
            if maximized:
                painter.drawRoundedRect(QRectF(cx - 4.5, cy - 2.5, 7, 7), 1, 1)
                painter.drawPolyline([QPointF(cx - 2.5, cy - 4.5), QPointF(cx + 4.5, cy - 4.5), QPointF(cx + 4.5, cy + 2.5)])
            else:
                painter.drawRoundedRect(QRectF(cx - 4.2, cy - 4.2, 8.4, 8.4), 1, 1)
        else:
            painter.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
            painter.drawLine(QPointF(cx + 4, cy - 4), QPointF(cx - 4, cy + 4))


def app_logo(size: int = 22, radius: int = 6, glyph: int = 14) -> QLabel:
    logo = QLabel()
    logo.setFixedSize(size, size)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    logo.setStyleSheet(f"background: {ACCENT}; border-radius: {radius}px;")
    logo.setPixmap(icons.pixmap("bolt", ON_ACCENT, glyph))
    return logo


class TitleBar(QFrame):
    toggle_theme = Signal()
    open_settings = Signal()

    def __init__(self, *, custom_controls: bool, left_inset: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)
        layout = hbox(self, (12 + left_inset, 0, 0 if custom_controls else 8, 0), 6)
        layout.addWidget(app_logo())
        layout.addSpacing(3)
        name = QLabel(APP_NAME)
        name.setObjectName("AppName")
        layout.addWidget(name)
        layout.addStretch(1)

        self.theme_button = IconButton("sun", "Switch to light theme", size=(30, 28))
        self.theme_button.clicked.connect(self.toggle_theme)
        settings = IconButton("sliders", "Settings", size=(30, 28))
        settings.clicked.connect(self.open_settings)
        layout.addWidget(self.theme_button)
        layout.addWidget(settings)

        if custom_controls:
            layout.addSpacing(6)
            for kind, tip, slot in (("min", "Minimize window", self._minimize),
                                    ("max", "Maximize window", self._toggle_maximize),
                                    ("close", "Close window", self._close)):
                btn = _WindowButton(kind, tip)
                btn.clicked.connect(slot)
                layout.addWidget(btn)
                btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        manager().changed.connect(self._sync_theme_icon)
        self._sync_theme_icon()

    def _sync_theme_icon(self) -> None:
        dark = theme().dark
        self.theme_button.set_icon("sun" if dark else "moon")
        tip = "Switch to light theme" if dark else "Switch to dark theme"
        self.theme_button.setToolTip(tip)
        self.theme_button.setAccessibleName(tip)

    def _minimize(self) -> None:
        self.window().showMinimized()

    def _toggle_maximize(self) -> None:
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()

    def _close(self) -> None:
        self.window().close()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()
