"""Modal dialog shown as a card over a dimmed window, plus header/footer helpers."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.common import IconButton, button, hbox, label, vbox


class OverlayDialog(QDialog):
    """A frameless dialog covering the parent window: scrim + centered card.

    Subclasses fill `self.card_layout`. Use `exec()`; `accept()`/`reject()` close it.
    """

    def __init__(self, parent: QWidget, width: int, height: int):
        super().__init__(parent.window(), Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self._card_size = (width, height)
        self.card = QFrame(self)
        self.card.setObjectName("DialogCard")
        self.card_layout: QVBoxLayout = vbox(self.card)
        self._rise = QPropertyAnimation(self.card, b"pos", self)
        self._rise.setDuration(200)
        self._rise.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(140)
        manager().changed.connect(self.update)

    # ------------------------------------------------------------ geometry
    def showEvent(self, event) -> None:  # noqa: N802
        host = self.parentWidget().window()
        self.setGeometry(host.frameGeometry() if host.isWindow() else host.geometry())
        self._layout_card()
        final = self.card.pos()
        self._rise.setStartValue(final + QPoint(0, 10))
        self._rise.setEndValue(final)
        self._rise.start()
        self.setWindowOpacity(0.0)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        super().showEvent(event)

    def _layout_card(self) -> None:
        w = min(self._card_size[0], self.width() - 32)
        h = min(self._card_size[1], self.height() - 32)
        self.card.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._layout_card()
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), t.c("scrim"))
        # Soft shadow under the card (cheaper than QGraphicsDropShadowEffect).
        card = QRectF(self.card.geometry())
        shadow = t.c("shadow")
        steps = 14
        for i in range(steps, 0, -1):
            color = QColor(shadow)
            color.setAlphaF(shadow.alphaF() * (1 - i / steps) ** 2 / 3)
            path = QPainterPath()
            spread = i * 2.0
            path.addRoundedRect(card.adjusted(-spread, -spread + 10, spread, spread + 14), 12 + spread, 12 + spread)
            painter.fillPath(path, color)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return  # never trigger buttons implicitly; dialogs handle Enter where it makes sense
        super().keyPressEvent(event)

    # ------------------------------------------------------------ builders
    def add_header(self, title: str, subtitle: str = "", *, icon: str | None = None,
                   bordered: bool = True, subtitle_widget: QWidget | None = None) -> QFrame:
        header = QFrame()
        if bordered:
            set_cls(header, "dialog-header")
        layout = hbox(header, (20, 18, 16, 14 if bordered else 0), 12)
        if icon:
            tile = QLabel()
            set_cls(tile, "icon-tile")
            tile.setFixedSize(34, 34)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            manager().bind_icon(tile, icon, "accent_text", 18)
            layout.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
        text = vbox(spacing=4)
        self.title_label = label(title, "h2")
        text.addWidget(self.title_label)
        if subtitle:
            sub = label(subtitle, "muted", wrap=True)
            sub.setTextFormat(Qt.TextFormat.RichText)
            text.addWidget(sub)
        if subtitle_widget:
            text.addWidget(subtitle_widget)
        layout.addLayout(text, 1)
        close = IconButton("x", "Close", size=(30, 30), icon_size=15, stroke=2)
        close.clicked.connect(self.reject)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.card_layout.addWidget(header)
        return header

    def add_footer(self, hint: QWidget | str = "", buttons: list[QPushButton] | None = None) -> QFrame:
        footer = QFrame()
        set_cls(footer, "dialog-footer")
        layout = hbox(footer, (20, 12, 16, 12), 8)
        if isinstance(hint, str):
            hint = label(hint, "hint", wrap=True)
        layout.addWidget(hint, 1)
        for btn in buttons or []:
            layout.addWidget(btn)
        self.card_layout.addWidget(footer)
        return footer

    @staticmethod
    def cancel_button(dialog: QDialog, text: str = "Cancel") -> QPushButton:
        return button(text, "secondary", height=34, on_click=dialog.reject)


def accent_html(text: str, mono: bool = True) -> str:
    """Inline span in the accent color (for rich-text labels)."""
    color = theme().c("accent_text").name()
    family = "font-family:'Geist Mono',monospace;" if mono else ""
    return f"<span style=\"{family}color:{color}\">{text}</span>"
