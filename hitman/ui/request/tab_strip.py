"""Strip of open request tabs, the new-tab button and the environment picker."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QWheelEvent
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

from hitman.core.models import method_short
from hitman.services.session import OpenTab
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import manager, theme
from hitman.ui.widgets.common import IconButton, SelectButton, hbox

TAB_WIDTH = 196


class _TabItem(QWidget):
    picked = Signal(str)
    close_requested = Signal(str)

    def __init__(self, tab_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab_id = tab_id
        self.method = "GET"
        self.title = ""
        self.dirty = False
        self.active = False
        self.setFixedWidth(TAB_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = hbox(self, (0, 0, 7, 0), 0)
        layout.addStretch(1)
        self.close_button = IconButton("x", "Close tab", size=(22, 22), icon_size=13, stroke=2, radius=5)
        self.close_button.clicked.connect(lambda: self.close_requested.emit(self.tab_id))
        policy = self.close_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.close_button.setSizePolicy(policy)
        layout.addWidget(self.close_button)
        manager().changed.connect(self.update)

    def set_state(self, tab: OpenTab, active: bool) -> None:
        self.method, self.title, self.dirty, self.active = tab.request.method, tab.request.name, tab.dirty, active
        self.setToolTip(tab.request.name)
        self.setAccessibleName(f"{tab.request.method} {tab.request.name}")
        self.close_button.setToolTip(f"Close {tab.request.name}")
        self.close_button.setVisible(active or self.underMouse())
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.close_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.close_button.setVisible(self.active)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.tab_id)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.close_requested.emit(self.tab_id)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.active:
            painter.fillRect(self.rect(), t.c("surface"))
            painter.fillRect(0, 0, self.width(), 2, t.c("accent_text"))
        painter.fillRect(self.width() - 1, 0, 1, self.height(), t.c("line"))
        x = 12.0
        painter.setFont(mono_font(10, 600))
        painter.setPen(t.method(self.method))
        label = method_short(self.method)
        mw = painter.fontMetrics().horizontalAdvance(label)
        painter.drawText(QRectF(x, 0, mw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, label)
        x += mw + 8
        right = self.close_button.geometry().left() - 6
        if self.dirty:
            right -= 7 + 6
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("accent_text"))
            painter.drawEllipse(QRectF(right + 6, self.height() / 2 - 3.5, 7, 7))
        painter.setFont(ui_font(12.5))
        painter.setPen(t.c("fg") if self.active else t.c("fg2"))
        width = max(0, int(right - x))
        text = painter.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRectF(x, 0, width, self.height()), Qt.AlignmentFlag.AlignVCenter, text)


class _TabScroller(QScrollArea):
    """Horizontal scroll area without a visible scrollbar; the wheel scrolls sideways."""

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.widget().width() if self.widget() else 0, 40)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(min(TAB_WIDTH, self.sizeHint().width()), 40)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)


class TabStrip(QFrame):
    tab_picked = Signal(str)
    tab_close = Signal(str)
    new_tab = Signal()
    env_menu = Signal(QWidget)
    quick_look = Signal(QWidget)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TabStrip")
        self.setFixedHeight(40)
        layout = hbox(self)
        self._scroll = _TabScroller()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._tabs_layout = hbox(self._inner)
        self._tabs_layout.addStretch(1)
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll, 0)

        self._plus = IconButton("plus", "New request", size=(40, 39), radius=0)
        self._plus.clicked.connect(self.new_tab)
        layout.addWidget(self._plus)
        layout.addStretch(1)

        right = hbox(margins=(10, 0, 10, 0), spacing=4)
        self.env_button = SelectButton("No environment", dot="fg3", height=28, margins=(10, 0, 8, 0),
                                       on_open=self.env_menu.emit)
        self.env_button.setObjectName("EnvSelect")
        self.env_button.setMinimumWidth(176)
        right.addWidget(self.env_button)
        self.eye = IconButton("eye", "Quick look at environment variables", size=(28, 28), icon_size=15, bordered=True)
        self.eye.clicked.connect(lambda: self.quick_look.emit(self.eye))
        right.addWidget(self.eye)
        layout.addLayout(right)
        self._items: dict[str, _TabItem] = {}

    def set_tabs(self, tabs: list[OpenTab], active_id: str) -> None:
        wanted = [t.id for t in tabs]
        for tab_id in list(self._items):
            if tab_id not in wanted:
                item = self._items.pop(tab_id)
                self._tabs_layout.removeWidget(item)
                item.deleteLater()
        for index, tab in enumerate(tabs):
            item = self._items.get(tab.id)
            if item is None:
                item = _TabItem(tab.id)
                item.picked.connect(self.tab_picked)
                item.close_requested.connect(self.tab_close)
                self._items[tab.id] = item
            self._tabs_layout.insertWidget(index, item)
            item.set_state(tab, tab.id == active_id)
        self._inner.setFixedWidth(TAB_WIDTH * len(tabs))
        self._scroll.setMaximumWidth(TAB_WIDTH * len(tabs))
        self._scroll.updateGeometry()
        active = self._items.get(active_id)
        if active:
            self._scroll.ensureWidgetVisible(active, 0, 0)

    def update_tab(self, tab: OpenTab, active: bool) -> None:
        item = self._items.get(tab.id)
        if item:
            item.set_state(tab, active)

    def set_environment(self, name: str, color: str) -> None:
        self.env_button.set_text(name)
        self.env_button.set_dot(color)
        self.env_button.setToolTip(f"Active environment: {name}")
