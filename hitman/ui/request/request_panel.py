"""Everything below the tab strip: header, URL bar, request sections and the response."""

from __future__ import annotations

from typing import Callable, Mapping

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QSplitter, QSplitterHandle, QWidget

from hitman.core.formatting import beautify_json
from hitman.core.http import ResolvedRequest, auto_headers
from hitman.core.models import METHODS
from hitman.core.urls import apply_params, apply_url
from hitman.services.session import OpenTab
from hitman.ui.request.request_editor import RequestEditor
from hitman.ui.request.request_header import RequestHeader
from hitman.ui.request.url_bar import UrlBar
from hitman.ui.response.response_panel import ResponsePanel
from hitman.ui.theme import manager, theme
from hitman.ui.widgets.common import vbox
from hitman.ui.widgets.popover import PopoverMenu


class _Handle(QSplitterHandle):
    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), t.c("surface"))
        w, h = self.width(), self.height()
        if self.orientation() == Qt.Orientation.Vertical:
            painter.fillRect(0, 0, w, 1, t.c("line"))
            painter.fillRect(0, h - 1, w, 1, t.c("line"))
            grip = QRectF(w / 2 - 16, h / 2 - 1.5, 32, 3)
        else:
            painter.fillRect(0, 0, 1, h, t.c("line"))
            painter.fillRect(w - 1, 0, 1, h, t.c("line"))
            grip = QRectF(w / 2 - 1.5, h / 2 - 16, 3, 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.c("line_strong"))
        painter.drawRoundedRect(grip, 1.5, 1.5)


class Splitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None):
        super().__init__(orientation, parent)
        self.setHandleWidth(9)
        self.setChildrenCollapsible(False)
        manager().changed.connect(self._repaint_handles)

    def _repaint_handles(self) -> None:
        for i in range(self.count()):
            self.handle(i).update()

    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return _Handle(self.orientation(), self)


class RequestPanel(QFrame):
    draft_changed = Signal(str)       # tab id
    send = Signal()
    cancel = Signal()
    save = Signal()
    save_menu = Signal(QWidget)
    open_code = Signal()
    curl_pasted = Signal(str)
    notify = Signal(str, str, bool)   # title, subtitle, is_error
    save_response = Signal()

    def __init__(self, scope: Callable[[], Mapping[str, str]], resolve: Callable[[OpenTab], ResolvedRequest],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MainColumn")
        self.tab: OpenTab | None = None
        self._resolve = resolve
        layout = vbox(self)
        self.header = RequestHeader()
        self.header.open_code.connect(self.open_code)
        self.header.save.connect(self.save)
        self.header.save_menu.connect(self.save_menu)
        self.header.rename.connect(self._rename)
        layout.addWidget(self.header)

        self.url_bar = UrlBar(scope)
        self.url_bar.url_edited.connect(self._on_url)
        self.url_bar.send.connect(self.send)
        self.url_bar.cancel.connect(self.cancel)
        self.url_bar.method_menu.connect(self._open_method_menu)
        self.url_bar.curl_pasted.connect(self.curl_pasted)
        layout.addWidget(self.url_bar)
        layout.addSpacing(6)

        self.splitter = Splitter(Qt.Orientation.Vertical)
        self.editor = RequestEditor()
        self.editor.setObjectName("RequestPane")
        self.editor.edited.connect(self._on_edit)
        self.editor.section_changed.connect(self._on_section)
        self.editor.send.connect(self.send)
        self.editor.beautify.connect(self._beautify)
        self.response = ResponsePanel()
        self.response.cancel.connect(self.cancel)
        self.response.notify.connect(lambda title, sub: self.notify.emit(title, sub, False))
        self.response.save_requested.connect(self.save_response)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.response)
        self.splitter.setStretchFactor(0, 100)
        self.splitter.setStretchFactor(1, 115)
        layout.addWidget(self.splitter, 1)

    # -------------------------------------------------------------- binding
    def bind(self, tab: OpenTab, breadcrumb: list[str], inherit_html: str) -> None:
        self.tab = tab
        request = tab.request
        self.url_bar.set_method(request.method)
        self.url_bar.set_url(request.url)
        self.url_bar.set_loading(tab.loading)
        self.editor.load(request, tab.section)
        self.editor.set_inherit_text(inherit_html)
        self.header.set_state(request.name, breadcrumb, tab.dirty)
        self.response.set_tab(tab)
        self.refresh_derived()

    def refresh_status(self, breadcrumb: list[str]) -> None:
        """Lightweight refresh after a draft/response/loading change of the bound tab."""
        if self.tab is None:
            return
        self.header.set_state(self.tab.request.name, breadcrumb, self.tab.dirty)
        self.url_bar.set_loading(self.tab.loading)
        self.response.set_tab(self.tab)

    def refresh_derived(self) -> None:
        """Recompute things that depend on variables: URL colors, 'Resolves to', auto headers."""
        if self.tab is None:
            return
        resolved = self._resolve(self.tab)
        self.url_bar.set_resolved(resolved.url)
        self.url_bar.url.rehighlight()
        self.editor.set_auto_headers(auto_headers(self.tab.request, resolved))

    def set_layout(self, side_by_side: bool) -> None:
        self.splitter.setOrientation(Qt.Orientation.Horizontal if side_by_side else Qt.Orientation.Vertical)
        total = self.splitter.width() if side_by_side else self.splitter.height()
        self.splitter.setSizes([int(total * 100 / 215), int(total * 115 / 215)])

    # ---------------------------------------------------------------- edits
    def _changed(self) -> None:
        if self.tab:
            self.refresh_derived()
            self.draft_changed.emit(self.tab.id)

    def _on_url(self, text: str) -> None:
        if self.tab is None:
            return
        apply_url(self.tab.request, text)
        self.editor.refresh_params()
        self._changed()

    def _on_edit(self, kind: str) -> None:
        if self.tab is None:
            return
        if kind == "params":
            apply_params(self.tab.request)
            self.url_bar.set_url(self.tab.request.url)
        self._changed()

    def _on_section(self, key: str) -> None:
        if self.tab:
            self.tab.section = key

    def _rename(self, name: str) -> None:
        if self.tab:
            self.tab.request.name = name
            self._changed()

    def _open_method_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self)
        current = self.tab.request.method if self.tab else "GET"
        for method in METHODS:
            menu.add_item(method, lambda m=method: self._set_method(m), checked=method == current,
                          role=method.lower(), mono=True)
        menu.show_at(anchor, width=170)

    def _set_method(self, method: str) -> None:
        if self.tab:
            self.tab.request.method = method
            self.url_bar.set_method(method)
            self._changed()

    def _beautify(self) -> None:
        if self.tab is None or self.tab.request.raw_type != "JSON":
            return
        try:
            pretty = beautify_json(self.tab.request.body)
        except ValueError as exc:
            self.notify.emit("Body is not valid JSON", str(exc)[:70], True)
            return
        self.editor.set_body_text(pretty)

    def focus_url(self) -> None:
        self.url_bar.focus_url()
