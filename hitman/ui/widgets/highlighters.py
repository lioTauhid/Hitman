"""Regex-based syntax highlighters that pull colors from the active theme."""

from __future__ import annotations

import re
from typing import Callable, Mapping

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from hitman.core.variables import VAR_RE, is_known
from hitman.ui.theme import theme


def _fmt(color: QColor, background: QColor | None = None) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(color)
    if background is not None:
        fmt.setBackground(background)
    return fmt


class _Base(QSyntaxHighlighter):
    def highlight_vars(self, text: str, start: int = 0, end: int | None = None) -> None:
        segment = text[start:end]
        for m in VAR_RE.finditer(segment):
            self.setFormat(start + m.start(), m.end() - m.start(), _fmt(theme().c("accent_text")))


class JsonHighlighter(_Base):
    TOKEN = re.compile(r'("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false)\b|\b(null)\b|([{}\[\],:])')

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        t = theme()
        for m in self.TOKEN.finditer(text):
            if m.group(1):
                role = "syn_key" if m.group(2) else "syn_str"
                self.setFormat(m.start(1), len(m.group(1)), _fmt(t.c(role)))
                self.highlight_vars(text, m.start(1), m.end(1))
                if m.group(2):
                    self.setFormat(m.start(2), len(m.group(2)), _fmt(t.c("syn_punc")))
            elif m.group(3):
                self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_num")))
            elif m.group(4):
                self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_bool")))
            elif m.group(5):
                self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_null")))
            elif m.group(6):
                self.setFormat(m.start(), 1, _fmt(t.c("syn_punc")))


class CodeHighlighter(_Base):
    """C-like or hash-comment languages: comments, strings, numbers, keywords, calls."""

    def __init__(self, document: QTextDocument, keywords: list[str], hash_comments: bool = False):
        super().__init__(document)
        self.keywords = set(keywords)
        comment = r"(#.*$)" if hash_comments else r"(//.*$)"
        self.token = re.compile(comment + r'|("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)'
                                r'|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)(\s*\()?|([^\s\w])')

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        t = theme()
        for m in self.token.finditer(text):
            if m.group(1):
                self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_com")))
            elif m.group(2):
                self.setFormat(m.start(), len(m.group(2)), _fmt(t.c("syn_str")))
                self.highlight_vars(text, m.start(2), m.end(2))
            elif m.group(3):
                self.setFormat(m.start(), len(m.group(3)), _fmt(t.c("syn_num")))
            elif m.group(4):
                word = m.group(4)
                if word in self.keywords:
                    role = "syn_kw"
                elif m.group(5):
                    role = "syn_fn"
                elif word[0].isupper() or word[0] == "$":
                    role = "syn_bool"
                else:
                    continue
                self.setFormat(m.start(4), len(word), _fmt(t.c(role)))
            elif m.group(6):
                self.setFormat(m.start(), 1, _fmt(t.c("syn_punc")))


class XmlHighlighter(_Base):
    TAG = re.compile(r"(</?)([\w:.-]+)|(/?>)")
    ATTR = re.compile(r'([\w:.-]+)(=)("[^"]*"|\'[^\']*\')')
    COMMENT = re.compile(r"<!--.*?-->")

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        t = theme()
        for m in self.TAG.finditer(text):
            if m.group(2):
                self.setFormat(m.start(1), len(m.group(1)), _fmt(t.c("syn_punc")))
                self.setFormat(m.start(2), len(m.group(2)), _fmt(t.c("syn_kw")))
            else:
                self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_punc")))
        for m in self.ATTR.finditer(text):
            self.setFormat(m.start(1), len(m.group(1)), _fmt(t.c("syn_key")))
            self.setFormat(m.start(3), len(m.group(3)), _fmt(t.c("syn_str")))
        for m in self.COMMENT.finditer(text):
            self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_com")))
        self.highlight_vars(text)


class VariableHighlighter(_Base):
    """Plain text with {{variables}} highlighted."""

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        self.highlight_vars(text)


class UrlHighlighter(QSyntaxHighlighter):
    """Colors a URL: known/unknown {{variables}}, :pathVars, query keys and separators."""

    TOKEN = re.compile(r"(\{\{[^}]*\}\})|(/:[A-Za-z_]\w*)|([?&=])|([^{/?&=]+|.)")

    def __init__(self, document: QTextDocument, scope: Callable[[], Mapping[str, str]]):
        super().__init__(document)
        self.scope = scope

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        t = theme()
        scope = self.scope()
        in_query, is_key = False, True
        err_bg = t.c("err")
        err_bg.setAlphaF(0.16)
        for m in self.TOKEN.finditer(text):
            if m.group(1):
                known = is_known(m.group(1)[2:-2], scope)
                fmt = _fmt(t.c("accent_text"), t.c("accent_soft")) if known else _fmt(t.c("err"), err_bg)
                self.setFormat(m.start(), len(m.group(1)), fmt)
            elif m.group(2):
                self.setFormat(m.start() + 1, len(m.group(2)) - 1, _fmt(t.c("patch")))
            elif m.group(3):
                sep = m.group(3)
                if sep == "?" and not in_query:
                    in_query, is_key = True, True
                elif sep == "&":
                    is_key = True
                elif sep == "=":
                    is_key = False
                self.setFormat(m.start(), 1, _fmt(t.c("fg3")))
            elif in_query and is_key:
                self.setFormat(m.start(), len(m.group(0)), _fmt(t.c("syn_key")))


KEYWORDS_JS = ["const", "let", "var", "function", "return", "if", "else", "for", "of", "in", "new", "await",
               "async", "true", "false", "null", "undefined", "typeof", "try", "catch", "throw"]


def for_language(document: QTextDocument, language: str) -> QSyntaxHighlighter | None:
    """Create the highlighter for a body/raw type ('JSON', 'XML', 'HTML', 'JavaScript', 'Text')."""
    if language == "JSON":
        return JsonHighlighter(document)
    if language in ("XML", "HTML"):
        return XmlHighlighter(document)
    if language == "JavaScript":
        return CodeHighlighter(document, KEYWORDS_JS)
    if language == "Text":
        return VariableHighlighter(document)
    return None
