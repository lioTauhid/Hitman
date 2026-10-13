"""Generate code dialog: snippets for the current request in several languages."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QButtonGroup, QFrame, QWidget

from hitman.core.codegen import HASH_COMMENTS, KEYWORDS, LANGUAGES, generate
from hitman.core.http import ResolvedRequest
from hitman.ui.dialogs.base import OverlayDialog
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.code_editor import CodeEditor
from hitman.ui.widgets.common import CardButton, ElidedLabel, RoleLabel, ToggleSwitch, button, hbox, label, vbox
from hitman.ui.widgets.highlighters import CodeHighlighter


class CodeDialog(OverlayDialog):
    def __init__(self, parent: QWidget, request: ResolvedRequest, last_language: str = "curl"):
        super().__init__(parent, 880, 600)
        self.request = request
        self.language = last_language if any(l[0] == last_language for l in LANGUAGES) else "curl"
        self._code = ""

        subtitle = QWidget()
        sub = hbox(subtitle, spacing=8)
        sub.addWidget(RoleLabel(request.method, lambda: theme().method(request.method), px=12, weight=600, mono=True))
        url = ElidedLabel(request.url, "fg2", px=12, mono=True)
        sub.addWidget(url, 1)
        self.add_header("Generate code", subtitle_widget=subtitle)

        content = hbox()
        side = QFrame()
        set_cls(side, "side-panel-bl")
        side.setFixedWidth(200)
        side_layout = vbox(side, (8, 10, 8, 10), 2)
        group = QButtonGroup(self)
        for key, name, lib in LANGUAGES:
            item = CardButton("nav-accent", f"{name} ({lib})")
            item.setChecked(key == self.language)
            item.setMinimumHeight(42)
            text = vbox(item, (12, 6, 12, 6), 1)
            text.addWidget(RoleLabel(name, "fg", px=12.5, weight=600 if key == self.language else 500))
            text.addWidget(RoleLabel(lib, "fg3", px=11))
            item.finish()
            group.addButton(item)
            item.clicked.connect(lambda _c=False, k=key: self._pick(k))
            side_layout.addWidget(item)
        side_layout.addStretch(1)
        content.addWidget(side)

        right = vbox()
        bar = QFrame()
        set_cls(bar, "bar")
        bar_layout = hbox(bar, (16, 10, 16, 10), 8)
        self.include_auth = ToggleSwitch(True, small=True)
        self.include_auth.setAccessibleName("Include auth header")
        self.include_auth.toggled.connect(lambda _on: self._render())
        bar_layout.addWidget(self.include_auth)
        bar_layout.addWidget(label("Include auth header", "body"))
        bar_layout.addStretch(1)
        self.stats = RoleLabel("", "fg3", px=11.5, mono=True)
        bar_layout.addWidget(self.stats)
        right.addWidget(bar)
        self.view = CodeEditor(read_only=True, framed=False, gutter_border=False)
        self.view.setStyleSheet("QPlainTextEdit { border-bottom-right-radius: 0; }")
        right.addWidget(self.view, 1)
        content.addLayout(right, 1)
        self.card_layout.addLayout(content, 1)

        self.copy_button = button("Copy snippet", "primary", icon="copy", icon_role="on_accent", icon_size=14,
                                  height=34, on_click=self._copy)
        close = self.cancel_button(self, "Close")
        self.add_footer("Variables are resolved with the active environment. Secrets are included, so review "
                        "before sharing.", [close, self.copy_button])
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._set_copied(False))
        self._render()

    def _pick(self, key: str) -> None:
        self.language = key
        self._render()

    def _render(self) -> None:
        self._code = generate(self.language, self.request, self.include_auth.isChecked())
        self.view.set_highlighter_factory(
            lambda doc: CodeHighlighter(doc, KEYWORDS.get(self.language, []), self.language in HASH_COMMENTS))
        self.view.set_text(self._code)
        name = next(n for k, n, _ in LANGUAGES if k == self.language)
        lines = self._code.count("\n") + 1
        self.stats.setText(f"{name} · {lines} lines")
        self._set_copied(False)

    def _set_copied(self, copied: bool) -> None:
        self.copy_button.setText("Copied" if copied else "Copy snippet")
        manager().bind_icon(self.copy_button, "check" if copied else "copy", "on_accent", 14)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._code)
        self._set_copied(True)
        self._timer.start(1600)
