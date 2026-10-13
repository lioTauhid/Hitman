"""History sidebar: recently sent requests grouped by day."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QStackedWidget, QStyledItemDelegate, QWidget

from hitman.core.models import HistoryEntry, method_short
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import manager, theme
from hitman.ui.widgets.common import IconButton, hbox, label, vbox


def _day_label(day: date) -> str:
    today = date.today()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return day.strftime("%a, %b %d") if day.year == today.year else day.strftime("%b %d, %Y")


def group_rows(entries: list[HistoryEntry]) -> list[tuple[str, object]]:
    """Return ("header", label) and ("entry", HistoryEntry) rows."""
    rows: list[tuple[str, object]] = []
    current = None
    for entry in entries:
        day = datetime.fromtimestamp(entry.created_at).date()
        if day != current:
            rows.append(("header", _day_label(day).upper()))
            current = day
        rows.append(("entry", entry))
    return rows


class _Model(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[str, object]] = []

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        kind, value = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return kind, value
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return value if kind == "header" else f"{value.method} {value.url}"
        return None


class _Delegate(QStyledItemDelegate):
    def __init__(self, view: _View):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        kind, _ = index.data(Qt.ItemDataRole.UserRole)
        return QSize(option.rect.width(), 32 if kind == "header" else 44)

    def paint(self, painter: QPainter, option, index) -> None:
        t = theme()
        kind, value = index.data(Qt.ItemDataRole.UserRole)
        rect = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "header":
            font = ui_font(11, 600)
            font.setLetterSpacing(font.SpacingType.AbsoluteSpacing, 0.66)
            painter.setFont(font)
            painter.setPen(t.c("fg3"))
            painter.drawText(rect.adjusted(8, 10, -8, -6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
            painter.restore()
            return
        entry: HistoryEntry = value
        if index.row() == self.view.hover_row:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("surface3"))
            painter.drawRoundedRect(rect, 7, 7)
        parts = urlsplit(entry.url) if "://" in entry.url else None
        path = (parts.path or "/") + (f"?{parts.query}" if parts and parts.query else "") if parts else entry.url
        host = parts.netloc if parts else ""
        code = str(entry.status) if entry.status else "ERR"
        time_text = datetime.fromtimestamp(entry.created_at).strftime("%H:%M")

        x, top, w = rect.left() + 8, rect.top(), rect.width()
        painter.setFont(mono_font(10, 600))
        painter.setPen(t.method(entry.method))
        painter.drawText(QRectF(x, top, 40, 44), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         method_short(entry.method))
        text_x = x + 48
        painter.setFont(mono_font(11, 600))
        code_w = painter.fontMetrics().horizontalAdvance(code)
        if not entry.status:
            painter.setPen(t.c("err"))
        else:
            painter.setPen(t.c("ok") if entry.status < 300 else t.c("warn"))
        painter.drawText(QRectF(rect.right() - 8 - code_w, top + 6, code_w, 17), Qt.AlignmentFlag.AlignVCenter, code)
        painter.setFont(ui_font(11))
        time_w = painter.fontMetrics().horizontalAdvance(time_text)
        painter.setPen(t.c("fg3"))
        painter.drawText(QRectF(rect.right() - 8 - time_w, top + 23, time_w, 15), Qt.AlignmentFlag.AlignVCenter, time_text)
        avail = w - 48 - 16 - max(code_w, time_w) - 8
        painter.setFont(mono_font(11.5))
        painter.setPen(t.c("fg"))
        painter.drawText(QRectF(text_x, top + 6, avail, 17), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(path, Qt.TextElideMode.ElideRight, int(avail)))
        painter.setFont(ui_font(11))
        painter.setPen(t.c("fg3"))
        painter.drawText(QRectF(text_x, top + 23, avail, 15), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(host, Qt.TextElideMode.ElideRight, int(avail)))
        painter.restore()


class _View(QListView):
    picked = Signal(object)

    def __init__(self):
        super().__init__()
        self.hover_row = -1
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(8, 0, 8, 16)
        self.setItemDelegate(_Delegate(self))
        self.viewport().setAutoFillBackground(False)
        self.clicked.connect(self._on_click)
        manager().changed.connect(self.viewport().update)

    def _on_click(self, index) -> None:
        kind, value = index.data(Qt.ItemDataRole.UserRole)
        if kind == "entry":
            self.picked.emit(value)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self.indexAt(event.position().toPoint())
        row = index.row() if index.isValid() and index.data(Qt.ItemDataRole.UserRole)[0] == "entry" else -1
        if row != self.hover_row:
            self.hover_row = row
            self.setCursor(Qt.CursorShape.PointingHandCursor if row >= 0 else Qt.CursorShape.ArrowCursor)
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hover_row = -1
        self.viewport().update()
        super().leaveEvent(event)


class HistoryPanel(QWidget):
    open_entry = Signal(object)  # HistoryEntry
    clear = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = vbox(self)
        header = QWidget()
        header.setFixedHeight(46)
        head = hbox(header, (16, 0, 8, 0), 4)
        head.addWidget(label("History", "panel-title"), 1)
        self._clear = IconButton("trash", "Clear history", icon_size=15)
        self._clear.clicked.connect(self.clear)
        head.addWidget(self._clear)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self.model = _Model(self)
        self.view = _View()
        self.view.setModel(self.model)
        self.view.picked.connect(self.open_entry)
        self.stack.addWidget(self.view)
        empty = label("Requests you send show up here.", "muted", wrap=True)
        empty.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        empty.setContentsMargins(16, 28, 16, 0)
        self.stack.addWidget(empty)
        layout.addWidget(self.stack, 1)

    def set_entries(self, entries: list[HistoryEntry]) -> None:
        self.model.set_rows(group_rows(entries))
        self.stack.setCurrentIndex(0 if entries else 1)
        self._clear.setEnabled(bool(entries))
