"""Monospace editor/viewer with a line-number gutter, pluggable highlighting and JSON folding."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QSyntaxHighlighter, QTextBlock, QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from hitman.core.formatting import fold_ranges
from hitman.ui import icons
from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets import highlighters

HIGHLIGHT_LIMIT = 400_000  # characters; larger documents are shown without colors
FOLD_WIDTH = 14  # gutter column for the fold chevrons


class _Gutter(QWidget):
    def __init__(self, editor: CodeEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.paint_gutter(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        foldable = self.editor.fold_line_at(event.position().y()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if foldable else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        line = self.editor.fold_line_at(event.position().y())
        if line is not None and event.button() == Qt.MouseButton.LeftButton:
            self.editor.toggle_fold(line)


class CodeEditor(QPlainTextEdit):
    submit = Signal()  # Ctrl/Cmd+Enter

    def __init__(self, *, read_only: bool = False, line_numbers: bool = True, wrap: bool = False,
                 framed: bool = True, gutter_border: bool = True, font_px: float | None = None,
                 folding: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._line_numbers = line_numbers
        # Folding (JSON only, needs the gutter): opening line -> closing line, and the folded openers.
        self._folding = folding and line_numbers
        self._folds: dict[int, int] = {}
        self._folded: set[int] = set()
        self._fold_markers: list[tuple[QRectF, int]] = []  # the clickable "…" after folded lines
        self._hovered = False
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
            self._gutter.setMouseTracking(self._folding)
            self.viewport().setMouseTracking(self._folding)
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
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits + (FOLD_WIDTH - 2 if self._folds else 0)

    def _update_margins(self, *_args) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        if self._gutter:
            cr = self.contentsRect()
            self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

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

    def enterEvent(self, event) -> None:  # noqa: N802
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hovered(False)
        super().leaveEvent(event)

    def _set_hovered(self, hovered: bool) -> None:
        # Like Postman, chevrons for open blocks show only while the pointer is over the editor.
        if self._folds and hovered != self._hovered:
            self._hovered = hovered
            self._gutter.update()

    def _next_shown(self, block: QTextBlock) -> QTextBlock:
        """The block after `block`, jumping over the lines a fold hides."""
        number = block.blockNumber()
        if number in self._folded:
            return self.document().findBlockByNumber(self._folds[number] + 1)
        return block.next()

    def paint_gutter(self, event) -> None:
        t = theme()
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), t.c("bg"))
        if self._gutter_border:
            painter.fillRect(QRect(self._gutter.width() - 1, event.rect().top(), 1, event.rect().height()), t.c("line"))
        painter.setFont(mono_font((self._font_px or manager().editor_font_size - 0.5) - 1))
        painter.setPen(t.c("fg3"))
        width = self._gutter.width()
        number_w = width - (FOLD_WIDTH + 6 if self._folds else 10)
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        line_h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                number = block.blockNumber()
                painter.drawText(0, top, number_w, line_h,
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(number + 1))
                folded = number in self._folded
                if number in self._folds and (folded or self._hovered):
                    rect = QRectF(width - FOLD_WIDTH - 2, top + (line_h - 12) / 2, 12, 12)
                    icons.paint(painter, "chevR" if folded else "chevD", t.c("fg2" if folded else "fg3"), rect, 2.2)
                top += round(self.blockBoundingRect(block).height())
            block = self._next_shown(block)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        self._fold_markers = []
        if not self._folded:
            return
        t = theme()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = self.fontMetrics()
        offset = self.contentOffset()
        block = self.firstVisibleBlock()
        while block.isValid():
            geometry = self.blockBoundingGeometry(block).translated(offset)
            if geometry.top() > event.rect().bottom():
                break
            number = block.blockNumber()
            if block.isVisible() and number in self._folded:
                layout = block.layout()
                line = layout.lineAt(layout.lineCount() - 1)
                x = geometry.left() + line.x() + line.naturalTextWidth() + 4
                y = geometry.top() + line.y()
                marker = QRectF(x, y + 2, metrics.horizontalAdvance("…") + 10, line.height() - 4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(t.c("line"))
                painter.drawRoundedRect(marker, 4, 4)
                painter.setPen(t.c("fg2"))
                painter.drawText(marker, Qt.AlignmentFlag.AlignCenter, "…")
                closing = self.document().findBlockByNumber(self._folds[number]).text().strip()
                painter.setPen(t.c("syn_punc"))
                painter.drawText(QRectF(marker.right() + 4, y, metrics.horizontalAdvance(closing) + 2, line.height()),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, closing)
                self._fold_markers.append((marker, number))
            block = self._next_shown(block)

    # --------------------------------------------------------------- folding
    def has_folds(self) -> bool:
        return bool(self._folds)

    def _refresh_folds(self) -> None:
        if self._folded:
            self.unfold_all()
        had_folds = bool(self._folds)
        self._folds = {}
        if self._folding and self._language == "JSON":
            lines = self.toPlainText().split("\n")
            if len(lines) != self.blockCount():  # U+2028 in a string reads as a newline but isn't a block
                lines = self._block_texts()
            self._folds = fold_ranges(lines)
        if bool(self._folds) != had_folds:  # the chevron column comes and goes with them
            self._update_margins()
        if self._gutter:
            self._gutter.update()

    def _block_texts(self):
        block = self.document().firstBlock()
        while block.isValid():
            yield block.text()
            block = block.next()

    def fold_line_at(self, y: float) -> int | None:
        """The foldable line drawn at gutter/viewport height `y`, if any."""
        if not self._folds:
            return None
        block = self.cursorForPosition(QPoint(0, round(y))).block()
        if self.blockBoundingGeometry(block).translated(self.contentOffset()).bottom() < y:
            return None  # below the last line
        return block.blockNumber() if block.blockNumber() in self._folds else None

    def toggle_fold(self, line: int) -> None:
        if line in self._folded:
            self.unfold(line)
        else:
            self.fold(line)

    def fold(self, line: int) -> None:
        end = self._folds.get(line)
        if end is None or line in self._folded:
            return
        self._folded.add(line)
        cursor = self.textCursor()
        if line < cursor.blockNumber() <= end:  # don't leave the cursor on a hidden line
            cursor.setPosition(self.document().findBlockByNumber(line).position())
            self.setTextCursor(cursor)
        self._show_lines(line, end)

    def unfold(self, line: int) -> None:
        if line in self._folded:
            self._folded.discard(line)
            self._show_lines(line, self._folds[line])

    def fold_all(self) -> None:
        if not self._folds:
            return
        self._folded = set(self._folds)
        self.go_to_start()
        self._show_lines(0, self.blockCount() - 1)

    def unfold_all(self) -> None:
        if not self._folds:
            return
        self._folded.clear()
        self._show_lines(0, self.blockCount() - 1)

    def reveal_line(self, line: int) -> None:
        """Unfold every block that hides `line`, outermost first."""
        for start in sorted(s for s in self._folded if s < line <= self._folds[s]):
            self.unfold(start)

    def _show_lines(self, first: int, last: int) -> None:
        """Set the visibility of lines first..last (first must be shown) from the folded set, then relayout.

        The document layout notices the visibility changes itself and resizes the scroll range.
        """
        doc = self.document()
        block = doc.findBlockByNumber(first)
        start = block.position()
        number, hide_until = first, first - 1
        while block.isValid() and number <= last:
            visible = number > hide_until
            if block.isVisible() != visible:
                block.setVisible(visible)
            if visible and number in self._folded:
                hide_until = self._folds[number]
            block, number = block.next(), number + 1
        last_block = doc.findBlockByNumber(min(last, doc.blockCount() - 1))
        doc.markContentsDirty(start, last_block.position() + last_block.length() - start)
        self.viewport().update()
        self._gutter.update()

    def find(self, *args) -> bool:
        """QPlainTextEdit.find that also unfolds the blocks hiding the match."""
        found = super().find(*args)
        if found and self._folded:
            self.reveal_line(self.textCursor().blockNumber())
            self.ensureCursorVisible()
        return found

    # ---------------------------------------------------------- highlighting
    def set_language(self, language: str | None) -> None:
        """Highlight as JSON / XML / HTML / JavaScript / Text, or None for plain."""
        self._language = language
        self._factory = (lambda doc: highlighters.for_language(doc, language)) if language else None
        self._install_highlighter()
        self._refresh_folds()

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
        self._folded.clear()  # the new blocks start out visible
        self.setPlainText(text)
        self._install_highlighter()
        self._refresh_folds()

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, event) -> None:  # noqa: N802
        for marker, line in self._fold_markers:
            if marker.contains(event.position()) and event.button() == Qt.MouseButton.LeftButton:
                self.unfold(line)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        if self._folding:
            on_marker = any(marker.contains(event.position()) for marker, _line in self._fold_markers)
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if on_marker else Qt.CursorShape.IBeamCursor)

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
