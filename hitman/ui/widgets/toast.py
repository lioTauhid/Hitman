"""Transient notification shown in the bottom-right corner of the window."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QWidget

from hitman.ui import icons
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import theme
from hitman.ui.widgets.common import RoleLabel, hbox, vbox


class Toast(QFrame):
    DURATION_MS = 3200

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("Toast")
        self.setMaximumWidth(440)
        layout = hbox(self, (12, 11, 14, 11), 12)
        self._badge = QLabel()
        self._badge.setFixedSize(24, 24)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        text = vbox(spacing=1)
        self._title = RoleLabel("", "fg", px=12.5, weight=600)
        self._sub = RoleLabel("", "fg3", px=11.5, mono=True)
        self._sub.setFont(mono_font(11.5))
        text.addWidget(self._title)
        text.addWidget(self._sub)
        layout.addLayout(text, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()
        host.installEventFilter(self)

    def show_message(self, title: str, sub: str = "", *, error: bool = False) -> None:
        t = theme()
        color = t.c("err") if error else t.c("accent")
        self._badge.setStyleSheet(f"background: {color.name()}; border-radius: 12px;")
        self._badge.setPixmap(icons.pixmap("x" if error else "check", t.c("on_accent") if not error else "#FFFFFF", 13, 2.6))
        self._title.setText(title)
        self._sub.setText(self._elide(sub))
        self._sub.setVisible(bool(sub))
        self._title.setFont(ui_font(12.5, 600))
        was_visible = self.isVisible()
        self.adjustSize()
        self._place()
        self.raise_()
        self.show()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity() if was_visible else 0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(self.DURATION_MS)

    def _elide(self, text: str) -> str:
        return self._sub.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, 380)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._fade.endValue() == 0.0:
            self.hide()

    def _place(self) -> None:
        host = self.parentWidget()
        self.move(host.width() - self.width() - 16, host.height() - self.height() - 42)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False
