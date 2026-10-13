"""Monospace editor/viewer with a line-number gutter and pluggable highlighting."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QSyntaxHighlighter, QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets import highlighters

HIGHLIGHT_LIMIT = 400_000  # characters; larger documents are shown without colors


class _Gutter(QWidget):
    def __init__(self, editor: CodeEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    submit = Signal()  # Ctrl/Cmd+Enter

    def __init__(self, *, read_only: bool = False, line_numbers: bool = True, wrap: bool = False,
                 framed: bool = True, gutter_border: bool = True, font_px: float | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._line_numbers = line_numbers
        self._gutter_border = gutter_border
        self._font_px = font_px
        self._highlighter: QSyntaxHighlighter | None = None
        self._language: str | None = None
        self._factory: Callable[[QTextDocument], QSyntaxHighlighter | None] | None = None
        set_cls(self, "" if framed else "plain")
        self.setReadOnly(read_only)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if wrap else QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.document().setDocumentMargin(10)
        self._gutter = _Gutter(self) if line_numbers else None
        if self._gutter:
            self.blockCountChanged.connect(self._update_margins)
            self.updateRequest.connect(self._scroll_gutter)
        manager().changed.connect(self._on_theme)
        self._on_theme()

    # ------------------------------------------------------------- styling
    def _on_theme(self) -> None:
        px = self._font_px or manager().editor_font_size - 0.5
        self.setFont(mono_font(px))
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 2)
        self._update_margins()
        if self._highlighter:
            self._highlighter.rehighlight()
        self.viewport().update()

    def gutter_width(self) -> int:
        if not self._line_numbers:
            return 0
        digits = max(3, len(str(self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self, *_args) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._gutter:
            cr = self.contentsRect()
            self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event) -> None:
        t = theme()
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), t.c("bg"))
        if self._gutter_border:
            painter.fillRect(QRect(self._gutter.width() - 1, event.rect().top(), 1, event.rect().height()), t.c("line"))
        painter.setFont(mono_font((self._font_px or manager().editor_font_size - 0.5) - 1))
        painter.setPen(t.c("fg3"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = round(self.blockBoundingRect(block).height())
        line_h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                painter.drawText(0, top, self._gutter.width() - 10, line_h,
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(number + 1))
            block = block.next()
            top += height
            height = round(self.blockBoundingRect(block).height()) if block.isValid() else height
            number += 1

    # ---------------------------------------------------------- highlighting
    def set_language(self, language: str | None) -> None:
        """Highlight as JSON / XML / HTML / JavaScript / Text, or None for plain."""
        self._language = language
        self._factory = (lambda doc: highlighters.for_language(doc, language)) if language else None
        self._install_highlighter()

    def set_highlighter_factory(self, factory: Callable[[QTextDocument], QSyntaxHighlighter | None]) -> None:
        self._factory = factory
        self._install_highlighter()

    def _install_highlighter(self) -> None:
        if self._highlighter:
            self._highlighter.setDocument(None)
            self._highlighter = None
        if self._factory and len(self.toPlainText()) <= HIGHLIGHT_LIMIT:
            self._highlighter = self._factory(self.document())

    def set_text(self, text: str) -> None:
        """Replace the content, keeping highlighting cheap for big documents."""
        if self._highlighter:
            self._highlighter.setDocument(None)
            self._highlighter = None
        self.setPlainText(text)
        self._install_highlighter()

    # ---------------------------------------------------------------- input
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key, mods = event.key(), event.modifiers()
        ctrl = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ctrl:
            self.submit.emit()
            return
        if self.isReadOnly():
            super().keyPressEvent(event)
            return
        if key == Qt.Key.Key_Tab and not mods:
            self.textCursor().insertText("  ")
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not mods:
            self._newline_with_indent()
            return
        super().keyPressEvent(event)

    def _newline_with_indent(self) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()
        indent = line[: len(line) - len(line.lstrip(" "))]
        before = line[: cursor.positionInBlock()].rstrip()
        if before.endswith(("{", "[")):
            indent += "  "
        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)

    def go_to_start(self) -> None:
        self.moveCursor(QTextCursor.MoveOperation.Start)
