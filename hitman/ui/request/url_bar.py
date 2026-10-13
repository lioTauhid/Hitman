"""Method picker, highlighted URL field, "Resolves to" hint and the Send/Cancel button."""

from __future__ import annotations

from typing import Callable, Mapping

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QPushButton, QStackedWidget, QWidget

from hitman.core.curl import looks_like_curl
from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.common import ElidedLabel, RoleLabel, SelectButton, Spinner, button, hbox
from hitman.ui.widgets.highlighters import UrlHighlighter

URL_HEIGHT = 38


class UrlEdit(QPlainTextEdit):
    """Single-line editor so the URL can be syntax-colored."""

    edited = Signal(str)
    submitted = Signal()
    curl_pasted = Signal(str)
    focus_changed = Signal(bool)

    def __init__(self, scope: Callable[[], Mapping[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        set_cls(self, "url")
        self._text = ""  # last known text; re-highlighting also fires textChanged, so compare
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setFixedHeight(URL_HEIGHT)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setPlaceholderText("Enter a URL or paste a cURL command")
        self.setAccessibleName("Request URL")
        self.document().setDocumentMargin(0)
        self.highlighter = UrlHighlighter(self.document(), scope)
        self.textChanged.connect(self._on_text_changed)
        manager().changed.connect(self._on_theme)
        self._on_theme()

    def _on_theme(self) -> None:
        self.setFont(mono_font(manager().editor_font_size))
        top = max(0, (URL_HEIGHT - self.fontMetrics().height()) // 2)
        self.setViewportMargins(12, top, 12, 0)
        self.highlighter.rehighlight()

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        if text == self.toPlainText():
            return
        self._text = text
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def rehighlight(self) -> None:
        self.highlighter.rehighlight()

    def _on_text_changed(self) -> None:
        text = self.toPlainText()
        if text != self._text:
            self._text = text
            self.edited.emit(text)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        text = source.text()
        if looks_like_curl(text):
            self.curl_pasted.emit(text)
            return
        self.textCursor().insertText(text.replace("\r", "").replace("\n", "").strip() if "\n" in text else text)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.focus_changed.emit(False)


class _ResolvePopup(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("ResolvePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = hbox(self, (10, 6, 10, 6), 8)
        layout.addWidget(RoleLabel("Resolves to", "fg3", px=11))
        self.value = ElidedLabel("", "fg", px=11.5, mono=True, elide=Qt.TextElideMode.ElideMiddle)
        layout.addWidget(self.value, 1)
        self.hide()


class UrlBar(QWidget):
    url_edited = Signal(str)
    send = Signal()
    cancel = Signal()
    method_menu = Signal(QWidget)
    curl_pasted = Signal(str)

    def __init__(self, scope: Callable[[], Mapping[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self._resolved = ""
        layout = hbox(self, (16, 10, 16, 0), 8)
        self.field = QFrame()
        self.field.setObjectName("UrlBar")
        self.field.setFixedHeight(40)
        field_layout = hbox(self.field, (1, 1, 1, 1), 0)
        self.method = SelectButton("GET", mono=True, weight=600, px=12.5, height=URL_HEIGHT, margins=(13, 0, 10, 0),
                                   on_open=self.method_menu.emit)
        self.method.setObjectName("MethodButton")
        self.method.setFixedWidth(107)
        field_layout.addWidget(self.method)
        self.url = UrlEdit(scope)
        self.url.edited.connect(self.url_edited)
        self.url.submitted.connect(self.send)
        self.url.curl_pasted.connect(self.curl_pasted)
        self.url.focus_changed.connect(lambda _f: self._sync_popup())
        field_layout.addWidget(self.url, 1)
        layout.addWidget(self.field, 1)

        self._buttons = QStackedWidget()
        self._buttons.setFixedSize(128, 40)
        send = button("Send", "primary", icon="send", icon_role="on_accent", on_click=self.send.emit)
        send.setObjectName("SendButton")
        send.setToolTip("Send request")
        self._buttons.addWidget(send)
        cancel = QPushButton()
        cancel.setObjectName("CancelSendButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.setAccessibleName("Cancel request")
        cancel_layout = hbox(cancel, (0, 0, 0, 0), 8)
        cancel_layout.addStretch(1)
        spinner = Spinner(15, ring=False, role="fg", width=2.2)
        spinner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cancel_layout.addWidget(spinner)
        cancel_text = RoleLabel("Cancel", "fg", px=13, weight=600)
        cancel_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cancel_layout.addWidget(cancel_text)
        cancel_layout.addStretch(1)
        cancel.clicked.connect(self.cancel)
        self._buttons.addWidget(cancel)
        layout.addWidget(self._buttons)
        self._popup: _ResolvePopup | None = None

    def set_method(self, method: str) -> None:
        self.method.set_text(method)
        self.method.set_role(lambda m=method: theme().method(m))
        self.method.setAccessibleName(f"HTTP method {method}")

    def set_url(self, url: str) -> None:
        self.url.set_text(url)

    def set_loading(self, loading: bool) -> None:
        self._buttons.setCurrentIndex(1 if loading else 0)

    def set_resolved(self, resolved: str) -> None:
        self._resolved = resolved
        self._sync_popup()

    def focus_url(self) -> None:
        self.url.setFocus()
        self.url.selectAll()

    # ---------------------------------------------------------- popup
    def _host(self) -> QWidget | None:
        window = self.window()
        return window.centralWidget() if hasattr(window, "centralWidget") else None

    def _sync_popup(self) -> None:
        raw = self.url.text().strip()
        show = self.url.hasFocus() and bool(raw) and self._resolved and self._resolved != raw
        host = self._host()
        if host is None:
            return
        if self._popup is None:
            self._popup = _ResolvePopup(host)
            self.field.installEventFilter(self)
        if not show:
            self._popup.hide()
            return
        self._popup.value.setText(self._resolved)
        self._place_popup()
        self._popup.raise_()
        self._popup.show()

    def _place_popup(self) -> None:
        host = self._host()
        origin = self.field.mapTo(host, QPoint(108, self.field.height() + 4))
        width = min(self.field.width() - 116, self._popup.value.sizeHint().width() + 100)
        self._popup.setGeometry(origin.x(), origin.y(), max(220, width), 30)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.field and event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and self._popup:
            if self._popup.isVisible():
                self._place_popup()
        return False
