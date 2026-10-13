"""Collections sidebar: filterable tree of collections, folders and requests."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QLineEdit, QListView, QStackedWidget,
                               QStyledItemDelegate, QStyleOptionViewItem, QWidget)

from hitman.core.models import Collection, Folder, Request, count_requests, method_short
from hitman.ui import icons
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.common import IconButton, SearchField, button, hbox, label, vbox

ROW_HEIGHT = 30
ROW_GAP = 1


@dataclass
class TreeRow:
    kind: str           # "collection" | "folder" | "request"
    id: str
    name: str
    depth: int
    collection_id: str
    expanded: bool = False
    method: str = ""
    count: int = 0


def build_rows(collections: list[Collection], expanded: set[str], query: str) -> list[TreeRow]:
    """Flatten the tree. With a query, every group is open and only matching requests are shown."""
    q = query.strip().lower()

    def matches(req: Request) -> bool:
        return not q or q in req.name.lower() or q in req.url.lower() or req.method.lower() == q

    def walk(items, depth: int, collection_id: str) -> list[TreeRow]:
        rows: list[TreeRow] = []
        for node in items:
            if isinstance(node, Folder):
                children = walk(node.items, depth + 1, collection_id)
                if q and not children:
                    continue
                is_open = bool(q) or node.id in expanded
                rows.append(TreeRow("folder", node.id, node.name, depth, collection_id, expanded=is_open))
                if is_open:
                    rows.extend(children)
            elif matches(node):
                rows.append(TreeRow("request", node.id, node.name, depth, collection_id, method=node.method))
        return rows

    out: list[TreeRow] = []
    for col in collections:
        children = walk(col.items, 1, col.id)
        if q and not children:
            continue
        is_open = bool(q) or col.id in expanded
        out.append(TreeRow("collection", col.id, col.name, 0, col.id, expanded=is_open,
                           count=count_requests(col.items)))
        if is_open:
            out.extend(children)
    return out


class TreeModel(QAbstractListModel):
    rename_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[TreeRow] = []

    def set_rows(self, rows: list[TreeRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.AccessibleTextRole):
            return row.name
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def flags(self, index: QModelIndex):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        name = str(value).strip()
        row = self.rows[index.row()]
        if name and name != row.name:
            self.rename_requested.emit(row.id, name)
        return True


def _layout(rect: QRect, row: TreeRow) -> dict[str, QRectF]:
    """Geometry of a row's parts, shared by painting, hit-testing and the rename editor."""
    x = rect.left() + 4 + row.depth * 14 + 4
    mid = rect.top() + ROW_HEIGHT / 2
    parts: dict[str, QRectF] = {}
    if row.kind == "request":
        parts["method"] = QRectF(x, rect.top(), 38, ROW_HEIGHT)
        x += 38 + 7
    else:
        parts["chevron"] = QRectF(x, mid - 6, 12, 12)
        x += 12 + 7
        parts["icon"] = QRectF(x, mid - 7.5, 15, 15)
        x += 15 + 7
    right = rect.right() - 3 - 24
    parts["more"] = QRectF(right, mid - 12, 24, 24)
    count_w = 22 if row.kind == "collection" else 0
    parts["count"] = QRectF(right - count_w - 4, rect.top(), count_w, ROW_HEIGHT)
    parts["name"] = QRectF(x, rect.top(), max(10, parts["count"].left() - x - 4), ROW_HEIGHT)
    return parts


class TreeDelegate(QStyledItemDelegate):
    def __init__(self, view: TreeView):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), ROW_HEIGHT + ROW_GAP)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row: TreeRow = index.data(Qt.ItemDataRole.UserRole)
        t = theme()
        rect = QRect(option.rect.left(), option.rect.top(), option.rect.width(), ROW_HEIGHT)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = row.kind == "request" and row.id == self.view.active_request_id
        hovered = index.row() == self.view.hover_row
        if active or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("accent_soft") if active else t.c("surface2"))
            painter.drawRoundedRect(QRectF(rect), 7, 7)
        parts = _layout(rect, row)
        if row.kind == "request":
            painter.setFont(mono_font(10, 600))
            painter.setPen(t.method(row.method))
            painter.drawText(parts["method"], Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             method_short(row.method))
            name_font, name_color = ui_font(12.5, 500 if active else 400), t.c("fg" if active else "fg2")
        else:
            chevron = parts["chevron"]
            painter.save()
            painter.translate(chevron.center())
            painter.setTransform(QTransform().rotate(90 if row.expanded else 0), True)
            icons.paint(painter, "chevR", t.c("fg3"), QRectF(-6, -6, 12, 12), 2.2)
            painter.restore()
            icon = "layers" if row.kind == "collection" else "folder"
            icons.paint(painter, icon, t.c("fg2" if row.kind == "collection" else "fg3"), parts["icon"])
            name_font = ui_font(12.5, 600 if row.kind == "collection" else 500)
            name_color = t.c("fg")
        if self.view.editing_row != index.row():
            painter.setFont(name_font)
            painter.setPen(name_color)
            text = painter.fontMetrics().elidedText(row.name, Qt.TextElideMode.ElideRight, int(parts["name"].width()))
            painter.drawText(parts["name"], Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if row.kind == "collection":
            painter.setFont(ui_font(11))
            painter.setPen(t.c("fg3"))
            painter.drawText(parts["count"], Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(row.count))
        if hovered or self.view.menu_row == index.row():
            more = parts["more"]
            if self.view.hover_more or self.view.menu_row == index.row():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(t.c("surface3"))
                painter.drawRoundedRect(more, 6, 6)
            icons.paint(painter, "more", t.c("fg2"), more.adjusted(4.5, 4.5, -4.5, -4.5), 3)
        painter.restore()

    def createEditor(self, parent: QWidget, option, index) -> QWidget:  # noqa: N802
        editor = QLineEdit(parent)
        set_cls(editor, "inline")
        editor.setFont(ui_font(12.5))
        return editor

    def setEditorData(self, editor: QLineEdit, index) -> None:  # noqa: N802
        editor.setText(index.data(Qt.ItemDataRole.EditRole))
        editor.selectAll()

    def updateEditorGeometry(self, editor: QWidget, option, index) -> None:  # noqa: N802
        row: TreeRow = index.data(Qt.ItemDataRole.UserRole)
        rect = QRect(option.rect.left(), option.rect.top(), option.rect.width(), ROW_HEIGHT)
        name = _layout(rect, row)["name"].toRect()
        editor.setGeometry(name.left() - 6, rect.top() + 3, rect.right() - name.left() - 2, ROW_HEIGHT - 6)


class TreeView(QListView):
    activated_row = Signal(object)          # TreeRow (click)
    menu_requested = Signal(object, QRect)  # TreeRow, global rect to anchor the menu

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.hover_row = -1
        self.hover_more = False
        self.menu_row = -1
        self.editing_row = -1
        self.active_request_id: str | None = None
        self._press_row = -1
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(8, 4, 8, 16)
        self.setItemDelegate(TreeDelegate(self))
        self.viewport().setAutoFillBackground(False)
        manager().changed.connect(self.viewport().update)

    def row_at(self, pos: QPoint) -> tuple[int, TreeRow | None]:
        index = self.indexAt(pos)
        if not index.isValid():
            return -1, None
        return index.row(), index.data(Qt.ItemDataRole.UserRole)

    def _more_rect(self, row_index: int) -> QRectF:
        index = self.model().index(row_index, 0)
        rect = self.visualRect(index)
        row = index.data(Qt.ItemDataRole.UserRole)
        return _layout(QRect(rect.left(), rect.top(), rect.width(), ROW_HEIGHT), row)["more"]

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        row_index, _row = self.row_at(event.position().toPoint())
        more = row_index >= 0 and self._more_rect(row_index).contains(event.position())
        if (row_index, more) != (self.hover_row, self.hover_more):
            self.hover_row, self.hover_more = row_index, more
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hover_row, self.hover_more = -1, False
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press_row = self.row_at(event.position().toPoint())[0] if event.button() == Qt.MouseButton.LeftButton else -1
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        row_index, row = self.row_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and row is not None and row_index == self._press_row:
            if self._more_rect(row_index).contains(event.position()):
                self._request_menu(row_index, row)
            else:
                self.activated_row.emit(row)
        self._press_row = -1
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        row_index, row = self.row_at(event.pos())
        if row is not None:
            self.menu_row = row_index
            self.viewport().update()
            self.menu_requested.emit(row, QRect(event.globalPos(), QSize(1, 1)))

    def _request_menu(self, row_index: int, row: TreeRow) -> None:
        more = self._more_rect(row_index).toRect()
        self.menu_row = row_index
        self.viewport().update()
        top_left = self.viewport().mapToGlobal(more.topLeft())
        self.menu_requested.emit(row, QRect(top_left, more.size()))

    def menu_closed(self) -> None:
        self.menu_row = -1
        self.viewport().update()

    def start_rename(self, node_id: str) -> None:
        for i, row in enumerate(self.model().rows):
            if row.id == node_id:
                index = self.model().index(i, 0)
                self.scrollTo(index)
                self.editing_row = i
                self.edit(index, QAbstractItemView.EditTrigger.AllEditTriggers, None)
                return

    def closeEditor(self, editor, hint) -> None:  # noqa: N802
        self.editing_row = -1
        super().closeEditor(editor, hint)
        self.viewport().update()


class CollectionsPanel(QWidget):
    new_collection = Signal()
    import_clicked = Signal()
    export_clicked = Signal()
    open_request = Signal(str)
    menu_requested = Signal(object, QRect)  # TreeRow, anchor rect
    rename_requested = Signal(str, str)
    expanded_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._collections: list[Collection] = []
        self.expanded: set[str] = set()

        layout = vbox(self)
        header = QWidget()
        header.setFixedHeight(46)
        head = hbox(header, (16, 0, 8, 0), 4)
        head.addWidget(label("Collections", "panel-title"), 1)
        add = IconButton("plus", "New collection")
        add.clicked.connect(self.new_collection)
        head.addWidget(add)
        layout.addWidget(header)

        actions = hbox(margins=(12, 0, 12, 0), spacing=6)
        actions.addWidget(button("Import", icon="import", icon_size=14, icon_role="fg", height=30,
                                 on_click=self.import_clicked.emit), 1)
        actions.addWidget(button("Export", icon="export", icon_size=14, icon_role="fg", height=30,
                                 on_click=self.export_clicked.emit), 1)
        layout.addLayout(actions)

        filter_box = vbox(margins=(12, 10, 12, 6))
        self.filter = SearchField("Filter requests")
        self.filter.edit.textChanged.connect(lambda _t: self.refresh())
        filter_box.addWidget(self.filter)
        layout.addLayout(filter_box)

        self.stack = QStackedWidget()
        self.model = TreeModel(self)
        self.model.rename_requested.connect(self.rename_requested)
        self.view = TreeView()
        self.view.setModel(self.model)
        self.view.activated_row.connect(self._on_activated)
        self.view.menu_requested.connect(self.menu_requested)
        self.stack.addWidget(self.view)

        self.no_match = label("", "muted", wrap=True)
        self.no_match.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.no_match.setContentsMargins(12, 28, 12, 0)
        self.stack.addWidget(self.no_match)

        empty = QWidget()
        empty_layout = vbox(empty, (20, 28, 20, 0), 10)
        message = label("No collections yet. Create one to group your requests, or import a file.", "muted", wrap=True)
        message.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(message)
        empty_layout.addWidget(button("New collection", "secondary", height=32, on_click=self.new_collection.emit))
        empty_layout.addStretch(1)
        self.stack.addWidget(empty)
        layout.addWidget(self.stack, 1)

    def set_collections(self, collections: list[Collection]) -> None:
        self._collections = collections
        self.refresh()

    def set_active_request(self, request_id: str | None) -> None:
        self.view.active_request_id = request_id
        self.view.viewport().update()

    def refresh(self) -> None:
        query = self.filter.text()
        rows = build_rows(self._collections, self.expanded, query)
        self.model.set_rows(rows)
        if not self._collections:
            self.stack.setCurrentIndex(2)
        elif query.strip() and not rows:
            self.no_match.setText(f"No requests match “{query.strip()}”.")
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

    def expand(self, *node_ids: str) -> None:
        self.expanded.update(i for i in node_ids if i)
        self.expanded_changed.emit(sorted(self.expanded))
        self.refresh()

    def _on_activated(self, row: TreeRow) -> None:
        if row.kind == "request":
            self.open_request.emit(row.id)
            return
        if self.filter.text().strip():
            return  # groups are forced open while filtering
        self.expanded.symmetric_difference_update({row.id})
        self.expanded_changed.emit(sorted(self.expanded))
        self.refresh()

    def focus_filter(self) -> None:
        self.filter.edit.setFocus()
        self.filter.edit.selectAll()
