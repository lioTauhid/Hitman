"""Bottom status bar: active environment, layout switch, SSL state and version."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from hitman import __version__
from hitman.ui.theme import manager
from hitman.ui.widgets.common import ColorDot, button, hbox


class StatusBar(QFrame):
    toggle_layout = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self.setFixedHeight(28)
        layout = hbox(self, (16, 0, 8, 0), 2)
        self._dot = ColorDot("fg3", 7)
        layout.addWidget(self._dot)
        layout.addSpacing(6)
        self._env = QLabel("No environment")
        layout.addWidget(self._env)
        layout.addStretch(1)
        self._layout_button = button("Stacked", "ghost", height=22, on_click=self.toggle_layout.emit)
        self._layout_button.setStyleSheet("padding: 0 8px; border-radius: 5px;")
        layout.addWidget(self._layout_button)
        self._ssl = QLabel("SSL verify on")
        self._ssl.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(self._ssl)
        version = QLabel(f"v{__version__}")
        version.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(version)

    def set_environment(self, name: str, color: str) -> None:
        self._env.setText(name)
        self._dot.set_token(color)

    def set_layout(self, side_by_side: bool) -> None:
        self._layout_button.setText("Side by side" if side_by_side else "Stacked")
        self._layout_button.setAccessibleName(f"Switch layout, now {self._layout_button.text()}")
        manager().bind_icon(self._layout_button, "cols" if side_by_side else "rows", "fg3", 13)

    def set_ssl(self, verify: bool) -> None:
        self._ssl.setText("SSL verify on" if verify else "SSL verify off")
