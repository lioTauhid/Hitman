"""Response viewer: status, timing, size, body (pretty/raw) and headers."""

from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPen, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QFrame, QHeaderView, QLabel, QLineEdit, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QWidget)

from hitman.core.formatting import detect_format, human_bytes, pretty_body
from hitman.core.http import HttpResponse
from hitman.services.session import OpenTab
from hitman.ui import icons
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.code_editor import CodeEditor
from hitman.ui.widgets.common import (IconButton, RoleLabel, SegmentedControl, Spinner, button, hbox, label,
                                      separator, vbox)
from hitman.ui.widgets.tabs import UnderlineTabs

MOD = "⌘" if sys.platform == "darwin" else "Ctrl"


class _EmptyArt(QWidget):
    """The 'no response yet' illustration from the design."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(72, 56)
        manager().changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(t.c("line_strong"), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(6, 10, 44, 34), 6, 6)
        for y, w in ((20, 20), (27, 28), (34, 14)):
            p.drawLine(14, y, 14 + w, y)
        p.setBrush(t.c("surface2"))
        p.drawEllipse(QRectF(42, 26, 24, 24))
        icons.paint(p, "bolt", t.c("accent"), QRectF(47, 31, 14, 14))


def _kbd(text: str) -> QLabel:
    return set_cls(QLabel(text), "kbd")


class StatusPill(QLabel):
    def __init__(self):
        super().__init__()
        self.setFont(mono_font(12, 600))
        self.setFixedHeight(22)
        self._code: int | None = None
        manager().changed.connect(self._apply)

    def set_status(self, code: int | None, text: str) -> None:
        self._code = code
        self.setText(text)
        self._apply()

    def _apply(self) -> None:
        color = theme().status(self._code)
        bg = theme().status(self._code)
        bg.setAlphaF(0.15)
        self.setStyleSheet(f"color: {color.name()}; background: {bg.name(bg.NameFormat.HexArgb)};"
                           " padding: 0 8px; border-radius: 6px;")


class ResponsePanel(QFrame):
    cancel = Signal()
    notify = Signal(str, str)
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ResponsePane")
        self.tab: OpenTab | None = None
        self._format = "Empty"
        self._shown_response: HttpResponse | None = None
        layout = vbox(self)

        # header row
        header = QFrame()
        header.setObjectName("ResponseHeader")
        header.setMinimumHeight(40)
        head = hbox(header, (10, 0, 10, 0), 10)
        self.tabs = UnderlineTabs([("body", "Body"), ("headers", "Headers")], height=40, count_style="plain",
                                  margins=(0, 0, 0, 0))
        self.tabs.changed.connect(self._on_section)
        head.addWidget(self.tabs)
        self._title = label("Response", "section")
        self._title.setContentsMargins(6, 0, 0, 0)
        head.addWidget(self._title)
        head.addStretch(1)
        self._meta = QWidget()
        meta = hbox(self._meta, spacing=12)
        self.status = StatusPill()
        meta.addWidget(self.status)
        self._time = RoleLabel("", "fg", px=12, weight=500, mono=True)
        self._size = RoleLabel("", "fg", px=12, weight=500, mono=True)
        for caption, value in (("Time", self._time), ("Size", self._size)):
            pair = hbox(spacing=4)
            pair.addWidget(label(caption, "hint"))
            pair.addWidget(value)
            meta.addLayout(pair)
        meta.addSpacing(2)
        meta.addWidget(separator())
        for icon, tip, slot in (("import", "Save response to a file", self.save_requested.emit),
                                ("copy", "Copy response", self._copy), ("x", "Clear response", self._clear)):
            btn = IconButton(icon, tip, icon_size=14, radius=6)
            btn.clicked.connect(slot)
            meta.addWidget(btn)
        head.addWidget(self._meta)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_idle())
        self.stack.addWidget(self._build_loading())
        self.stack.addWidget(self._build_error())
        self.stack.addWidget(self._build_body())
        self.stack.addWidget(self._build_headers())
        layout.addWidget(self.stack, 1)
        self.set_tab(None)

    # ------------------------------------------------------------- pages
    def _centered(self, *widgets: QWidget, spacing: int = 10) -> QWidget:
        page = QWidget()
        outer = vbox(page, (24, 24, 24, 24))
        outer.addStretch(1)
        inner = vbox(spacing=spacing)
        for widget in widgets:
            inner.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addLayout(inner)
        outer.addStretch(1)
        return page

    def _build_idle(self) -> QWidget:
        title = RoleLabel("No response yet", "fg", px=13.5, weight=600)
        text = label("Send the request to see the response body and headers here.", "muted", wrap=True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setMaximumWidth(340)
        keys = QWidget()
        row = hbox(keys, spacing=4)
        row.addWidget(_kbd(MOD))
        row.addWidget(label("+", "small"))
        row.addWidget(_kbd("Enter"))
        row.addSpacing(4)
        row.addWidget(label("to send", "small"))
        return self._centered(_EmptyArt(), title, text, keys)

    def _build_loading(self) -> QWidget:
        cancel = button("Cancel", "secondary", height=28, on_click=self.cancel.emit)
        cancel.setStyleSheet("font-size: 12px; padding: 0 12px; border-radius: 7px; min-height: 26px;")
        return self._centered(Spinner(28), RoleLabel("Sending request…", "fg2", px=12.5), cancel, spacing=12)

    def _build_error(self) -> QWidget:
        icon = QLabel()
        manager().bind_icon(icon, "xCircle", "err", 28)
        title = RoleLabel("Could not send the request", "fg", px=13.5, weight=600)
        self._error = label("", "muted", wrap=True, selectable=True)
        self._error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error.setMaximumWidth(460)
        return self._centered(icon, title, self._error)

    def _build_body(self) -> QWidget:
        page = QWidget()
        layout = vbox(page)
        bar = hbox(margins=(12, 8, 12, 8), spacing=8)
        self.views = SegmentedControl([("pretty", "Pretty"), ("raw", "Raw")])
        self.views.changed.connect(self._on_view)
        bar.addWidget(self.views)
        self._format_badge = label("JSON", "format")
        self._format_badge.setFixedHeight(24)
        bar.addWidget(self._format_badge)
        bar.addStretch(1)
        self._find_button = IconButton("search", "Search in response", icon_size=14, role="fg3", radius=6)
        self._find_button.clicked.connect(self._toggle_find)
        bar.addWidget(self._find_button)
        layout.addLayout(bar)

        self.find_bar = QFrame()
        self.find_bar.setObjectName("FindBar")
        find = hbox(self.find_bar, (12, 6, 12, 6), 6)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in response")
        self.find_input.setFixedHeight(28)
        self.find_input.textChanged.connect(lambda _t: self._find(restart=True))
        self.find_input.returnPressed.connect(lambda: self._find())
        find.addWidget(self.find_input, 1)
        self._find_count = label("", "small")
        find.addWidget(self._find_count)
        for icon, tip, back in (("up", "Previous match", True), ("down", "Next match", False)):
            btn = IconButton(icon, tip, size=(26, 26), icon_size=14, radius=6)
            btn.clicked.connect(lambda _c=False, b=back: self._find(backward=b))
            find.addWidget(btn)
        close = IconButton("x", "Close search", size=(26, 26), icon_size=13, radius=6)
        close.clicked.connect(self._toggle_find)
        find.addWidget(close)
        self.find_bar.hide()
        layout.addWidget(self.find_bar)

        self.body_stack = QStackedWidget()
        empty = label("This response has no body.", "muted")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_stack.addWidget(empty)
        self.pretty = CodeEditor(read_only=True, framed=False, gutter_border=False)
        self.pretty.setAccessibleName("Response body")
        self.body_stack.addWidget(self.pretty)
        self.raw = CodeEditor(read_only=True, framed=False, line_numbers=False, wrap=True)
        self.raw.setAccessibleName("Raw response body")
        self.body_stack.addWidget(self.raw)
        binary = label("", "muted", wrap=True)
        binary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._binary = binary
        self.body_stack.addWidget(binary)
        frame = QFrame()
        frame.setObjectName("BodyFrame")
        frame_layout = vbox(frame)
        frame_layout.addWidget(self.body_stack)
        layout.addWidget(frame, 1)
        return page

    def _build_headers(self) -> QWidget:
        page = QWidget()
        layout = vbox(page, (16, 12, 16, 12))
        self.headers_table = QTableWidget(0, 2)
        self.headers_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.headers_table.verticalHeader().hide()
        self.headers_table.setWordWrap(True)
        self.headers_table.setShowGrid(False)
        self.headers_table.setFrameShape(QFrame.Shape.NoFrame)
        self.headers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.headers_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.headers_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.headers_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setFixedHeight(30)
        self.headers_table.setObjectName("HeadersTable")
        self.headers_table.setFont(mono_font(12))
        header.setFont(ui_font(11.5, 500))
        layout.addWidget(self.headers_table)
        return page

    # ------------------------------------------------------------- state
    def set_tab(self, tab: OpenTab | None) -> None:
        self.tab = tab
        response = tab.response if tab else None
        loading = bool(tab and tab.loading)
        has = response is not None and response.ok and not loading
        self.tabs.setVisible(has)
        self._meta.setVisible(has)
        self._title.setVisible(not has)
        if loading:
            self.stack.setCurrentIndex(1)
            return
        if response is None:
            self.stack.setCurrentIndex(0)
            return
        if not response.ok:
            self._error.setText(response.error or "Unknown error")
            self.stack.setCurrentIndex(2)
            return
        if response is not self._shown_response:
            self._show_response(response)
        self.tabs.set_current(tab.response_section)
        self.views.set_value(tab.response_view)
        self._sync_body_page()

    def _show_response(self, response: HttpResponse) -> None:
        self._shown_response = response
        text = f"{response.status_code} {response.reason}".strip()
        self.status.set_status(response.status_code, text)
        self._time.setText(f"{response.elapsed_ms} ms")
        self._size.setText(human_bytes(response.size))
        self.tabs.set_count("headers", len(response.headers))
        self._format = detect_format(response.content_type, response.body)
        self._format_badge.setText(self._format)
        if self._format == "Binary":
            self._binary.setText(f"Binary response · {human_bytes(len(response.body))}. Save it to a file to open it.")
        elif self._format != "Empty":
            text_body = response.text()
            self.raw.set_text(text_body)
            self.pretty.set_text(pretty_body(text_body, self._format))
            self.pretty.set_language({"JSON": "JSON", "XML": "XML", "HTML": "HTML"}.get(self._format))
        self.headers_table.setRowCount(len(response.headers))
        for row, (key, value) in enumerate(response.headers):
            key_item = QTableWidgetItem(key)
            key_item.setForeground(theme().c("fg2"))
            self.headers_table.setItem(row, 0, key_item)
            self.headers_table.setItem(row, 1, QTableWidgetItem(value))
        self.headers_table.setColumnWidth(0, 220)
        self.headers_table.resizeRowsToContents()

    def _sync_body_page(self) -> None:
        if self.tab is None:
            return
        if self.tab.response_section == "headers":
            self.stack.setCurrentIndex(4)
            return
        self.stack.setCurrentIndex(3)
        if self._format == "Empty":
            self.body_stack.setCurrentIndex(0)
        elif self._format == "Binary":
            self.body_stack.setCurrentIndex(3)
        else:
            self.body_stack.setCurrentIndex(1 if self.tab.response_view == "pretty" else 2)
        self.views.setVisible(self._format not in ("Empty", "Binary"))
        self._find_button.setVisible(self._format not in ("Empty", "Binary"))

    def _on_section(self, key: str) -> None:
        if self.tab:
            self.tab.response_section = key
            self._sync_body_page()

    def _on_view(self, key: str) -> None:
        if self.tab:
            self.tab.response_view = key
            self._sync_body_page()
            self._find(restart=True)

    # ------------------------------------------------------------ actions
    def _copy(self) -> None:
        response = self.tab.response if self.tab else None
        if response and response.ok:
            QGuiApplication.clipboard().setText(response.text())
            self.notify.emit("Response copied", human_bytes(len(response.body)))

    def _clear(self) -> None:
        if self.tab:
            self.tab.response = None
            self._shown_response = None
            self.set_tab(self.tab)

    def _toggle_find(self) -> None:
        show = not self.find_bar.isVisible()
        self.find_bar.setVisible(show)
        if show:
            self.find_input.setFocus()
            self.find_input.selectAll()
            self._find(restart=True)
        else:
            self._find_count.setText("")

    def _active_view(self) -> CodeEditor:
        return self.pretty if self.body_stack.currentIndex() == 1 else self.raw

    def _find(self, backward: bool = False, restart: bool = False) -> None:
        view, needle = self._active_view(), self.find_input.text()
        if not needle:
            self._find_count.setText("")
            return
        if restart:
            view.go_to_start()
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        found = view.find(needle, flags)
        if not found:  # wrap around
            if backward:
                view.moveCursor(QTextCursor.MoveOperation.End)
            else:
                view.go_to_start()
            found = view.find(needle, flags)
        total = view.toPlainText().lower().count(needle.lower())
        self._find_count.setText(f"{total} match{'es' if total != 1 else ''}" if found else "No matches")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.find_bar.isVisible():
            self._toggle_find()
            return
        super().keyPressEvent(event)

    def current_text(self) -> str:
        response = self.tab.response if self.tab else None
        return response.text() if response and response.ok else ""

    @property
    def format(self) -> str:
        return self._format
