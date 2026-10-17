"""Request sections: Params, Authorization, Headers and Body."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QButtonGroup, QFrame, QLabel, QLineEdit, QRadioButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QWidget)

from hitman.core.models import AUTH_LABELS, AUTH_TYPES, BODY_MODE_LABELS, BODY_MODES, RAW_TYPES, Auth, Request
from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls
from hitman.ui.widgets.code_editor import CodeEditor
from hitman.ui.widgets.common import IconButton, SelectButton, button, hbox, label, vbox
from hitman.ui.widgets.key_value import KeyValueEditor, SimpleTable
from hitman.ui.widgets.popover import PopoverMenu
from hitman.ui.widgets.tabs import UnderlineTabs

SECTIONS = [("params", "Params"), ("auth", "Authorization"), ("headers", "Headers"), ("body", "Body")]


def _page() -> tuple[QScrollArea, QWidget]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    scroll.setWidget(body)
    return scroll, body


def _field(caption: str, edit: QLineEdit) -> QWidget:
    box = QWidget()
    layout = vbox(box, spacing=6)
    layout.addWidget(label(caption, "section"))
    layout.addWidget(edit)
    return box


def _input(placeholder: str, mono: bool = True) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setAccessibleName(placeholder)
    edit.setFixedHeight(34)
    if mono:
        edit.setProperty("mono", "true")
        edit.setFont(mono_font(12.5))
    return edit


def _title_row(title: str, hint_text: str = "", bulk: QWidget | None = None) -> tuple:
    row = hbox(spacing=10)
    row.addWidget(label(title, "section"))
    hint = label(hint_text, "small")
    row.addWidget(hint)
    row.addStretch(1)
    if bulk:
        row.addWidget(bulk)
    return row, hint


class RequestEditor(QWidget):
    edited = Signal(str)            # "params" | "path_vars" | "headers" | "auth" | "body"
    section_changed = Signal(str)
    send = Signal()
    beautify = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.request: Request = Request()
        self._loading = False
        layout = vbox(self)
        tabs_frame = QFrame()
        tabs_frame.setObjectName("SectionTabs")
        tabs_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tabs_layout = vbox(tabs_frame)
        self.tabs = UnderlineTabs(SECTIONS)
        self.tabs.changed.connect(self._on_section)
        tabs_layout.addWidget(self.tabs)
        layout.addWidget(tabs_frame)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_params())
        self.pages.addWidget(self._build_auth())
        self.pages.addWidget(self._build_headers())
        self.pages.addWidget(self._build_body())
        # May shrink to nothing so the section tabs stay whole when the response is maximized.
        self.pages.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.pages, 1)

    # ================================================================ pages
    def _build_params(self) -> QWidget:
        scroll, body = _page()
        layout = vbox(body, (16, 14, 16, 18), 12)
        self._params_bulk = button("Bulk edit", "link-muted", on_click=lambda: self._toggle_bulk(self.params_table, self._params_bulk))
        row, _ = _title_row("Query parameters", "Kept in sync with the URL", self._params_bulk)
        layout.addLayout(row)
        self.params_table = KeyValueEditor()
        self.params_table.changed.connect(lambda: self._edit("params"))
        layout.addWidget(self.params_table)
        self._path_title = label("Path variables", "section")
        self._path_title.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self._path_title)
        self.path_table = KeyValueEditor(fixed_keys=True, header=False)
        self.path_table.changed.connect(lambda: self._edit("path_vars"))
        layout.addWidget(self.path_table)
        layout.addStretch(1)
        return scroll

    def _build_auth(self) -> QWidget:
        scroll, body = _page()
        outer = hbox(body, (16, 14, 16, 18), 28)
        left = vbox(spacing=8)
        left.addWidget(label("Auth type", "section"))
        self.auth_type = SelectButton("Inherit from parent", on_open=self._open_auth_menu)
        self.auth_type.setFixedWidth(260)
        left.addWidget(self.auth_type)
        note = label("The authorization header is generated automatically when you send the request.", "hint", wrap=True)
        note.setFixedWidth(260)
        left.addWidget(note)
        left.addStretch(1)
        outer.addLayout(left)

        self.auth_pages = QStackedWidget()
        self._inherit_box = self._dashed("")
        self._inherit_box_label: QLabel = self._inherit_box.findChild(QLabel)
        self.auth_pages.addWidget(self._top_aligned(self._inherit_box))
        self.auth_pages.addWidget(self._top_aligned(self._dashed("This request does not use any authorization.")))

        bearer = QWidget()
        bearer_layout = vbox(bearer, spacing=12)
        self.token = _input("Paste a token or use a variable")
        bearer_layout.addWidget(_field("Token", self.token))
        sent_as = label("", "hint")
        sent_as.setTextFormat(Qt.TextFormat.RichText)
        sent_as.setText("Sent as <span style=\"font-family:'Geist Mono',monospace\">Authorization: Bearer &lt;token&gt;</span>")
        bearer_layout.addWidget(sent_as)
        bearer_layout.addStretch(1)
        self.auth_pages.addWidget(bearer)

        basic = QWidget()
        basic_layout = vbox(basic, spacing=12)
        self.username = _input("Username", mono=False)
        basic_layout.addWidget(_field("Username", self.username))
        self.password = _input("Password", mono=False)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        pw_box = QWidget()
        pw_layout = vbox(pw_box, spacing=6)
        pw_layout.addWidget(label("Password", "section"))
        pw_row = hbox(spacing=6)
        pw_row.addWidget(self.password, 1)
        reveal = IconButton("eye", "Show or hide password", size=(34, 34), icon_size=15, role="fg3")
        reveal.clicked.connect(self._toggle_password)
        pw_row.addWidget(reveal)
        pw_layout.addLayout(pw_row)
        basic_layout.addWidget(pw_box)
        basic_layout.addStretch(1)
        self.auth_pages.addWidget(basic)

        apikey = QWidget()
        api_layout = vbox(apikey, spacing=12)
        pair = hbox(spacing=12)
        self.api_key = _input("X-API-Key")
        self.api_value = _input("Value")
        pair.addWidget(_field("Key", self.api_key), 1)
        pair.addWidget(_field("Value", self.api_value), 1)
        api_layout.addLayout(pair)
        add_to = hbox(spacing=16)
        add_to.addWidget(label("Add to", "section"))
        self.add_header = QRadioButton("Header")
        self.add_query = QRadioButton("Query params")
        group = QButtonGroup(apikey)
        for radio in (self.add_header, self.add_query):
            group.addButton(radio)
            add_to.addWidget(radio)
        add_to.addStretch(1)
        api_layout.addLayout(add_to)
        api_layout.addStretch(1)
        self.auth_pages.addWidget(apikey)
        outer.addWidget(self.auth_pages, 1)

        for edit in (self.token, self.username, self.password, self.api_key, self.api_value):
            edit.textEdited.connect(lambda _t: self._sync_auth())
        self.add_header.toggled.connect(lambda _on: self._sync_auth())
        return scroll

    def _build_headers(self) -> QWidget:
        scroll, body = _page()
        layout = vbox(body, (16, 14, 16, 18), 12)
        self._headers_bulk = button("Bulk edit", "link-muted", on_click=lambda: self._toggle_bulk(self.headers_table, self._headers_bulk))
        row, _ = _title_row("Headers", "", self._headers_bulk)
        layout.addLayout(row)
        self.headers_table = KeyValueEditor()
        self.headers_table.changed.connect(lambda: self._edit("headers"))
        layout.addWidget(self.headers_table)
        self._auto_toggle = button("", "link-muted", icon="chevR", icon_role="fg3", icon_size=12)
        self._auto_toggle.clicked.connect(self._toggle_auto)
        layout.addWidget(self._auto_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.auto_table = SimpleTable([("Key", 100), ("Value", 125), ("Description", 110)], header=False,
                                      mono=(True, True, False), roles=("fg2", "fg2", "fg3"), px=12, row_height=32,
                                      lead_icon="lock", muted=True, column_lines=False)
        self.auto_table.hide()
        layout.addWidget(self.auto_table)
        layout.addStretch(1)
        self._auto_rows: list[tuple[str, str, str]] = []
        self._show_auto = False
        return scroll

    def _build_body(self) -> QWidget:
        page = QWidget()
        layout = vbox(page, (16, 14, 16, 18), 12)
        top = hbox(spacing=16)
        self._mode_group = QButtonGroup(page)
        self._mode_buttons: dict[str, QRadioButton] = {}
        for mode in BODY_MODES:
            radio = QRadioButton(BODY_MODE_LABELS[mode])
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self._mode_group.addButton(radio)
            self._mode_buttons[mode] = radio
            top.addWidget(radio)
            radio.toggled.connect(lambda on, m=mode: on and self._set_body_mode(m))
        top.addStretch(1)
        self.raw_type = SelectButton("JSON", px=12, weight=600, role="accent_text", height=26, margins=(10, 0, 8, 0),
                                     on_open=self._open_raw_menu)
        self.raw_type.setStyleSheet("QPushButton { border-radius: 6px; }")
        top.addWidget(self.raw_type)
        self._beautify = button("Beautify", "link-muted", on_click=self.beautify.emit)
        top.addWidget(self._beautify)
        layout.addLayout(top)

        self.body_pages = QStackedWidget()
        none_box = self._dashed("This request does not have a body.", centered=True)
        none_box.setMinimumHeight(60)
        self.body_pages.addWidget(none_box)

        form_page, form_body = _page()
        form_layout = vbox(form_body, spacing=12)
        self._form_bulk = button("Bulk edit", "link-muted", on_click=lambda: self._toggle_bulk(self.form_table, self._form_bulk))
        form_title, self._form_hint = _title_row("Form fields", "", self._form_bulk)
        form_layout.addLayout(form_title)
        self.form_table = KeyValueEditor(allow_files=True)
        self.form_table.changed.connect(lambda: self._edit("body"))
        form_layout.addWidget(self.form_table)
        form_layout.addStretch(1)
        self.body_pages.addWidget(form_page)

        self.editor = CodeEditor()
        self.editor.setAccessibleName("Request body")
        self.editor.setMinimumHeight(60)
        self.editor.textChanged.connect(self._on_body_text)
        self.editor.submit.connect(self.send)
        self.body_pages.addWidget(self.editor)
        layout.addWidget(self.body_pages, 1)
        return page

    @staticmethod
    def _dashed(text: str, centered: bool = False) -> QFrame:
        box = QFrame()
        set_cls(box, "dashed-box")
        layout = vbox(box, (14, 12, 14, 12))
        text_label = label(text, "muted", wrap=True)
        text_label.setTextFormat(Qt.TextFormat.RichText)
        if centered:
            text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label)
        return box

    @staticmethod
    def _top_aligned(widget: QWidget) -> QWidget:
        holder = QWidget()
        layout = vbox(holder)
        layout.addWidget(widget)
        layout.addStretch(1)
        return holder

    # ============================================================== loading
    def load(self, request: Request, section: str) -> None:
        """Show `request` (the draft object is edited in place)."""
        self._loading = True
        self.request = request
        self.tabs.set_current(section)
        self.pages.setCurrentIndex([k for k, _ in SECTIONS].index(section))
        self.params_table.set_rows(request.params)
        self.refresh_path_vars()
        self.headers_table.set_rows(request.headers)
        self._load_auth(request.auth)
        self._mode_buttons[request.body_mode].setChecked(True)
        self.form_table.set_rows(request.form)
        if self.editor.toPlainText() != request.body:
            self.editor.set_text(request.body)
        self.editor.set_language(request.raw_type)
        self.raw_type.set_text(request.raw_type)
        self._show_body_page()
        self._update_counts()
        self._loading = False

    def refresh_params(self) -> None:
        """Called after the URL changed."""
        self._loading = True
        self.params_table.set_rows(self.request.params)
        self.refresh_path_vars()
        self._update_counts()
        self._loading = False

    def refresh_path_vars(self) -> None:
        self.path_table.set_rows(self.request.path_vars)
        has = bool(self.request.path_vars)
        self._path_title.setVisible(has)
        self.path_table.setVisible(has)

    def set_inherit_text(self, html: str) -> None:
        self._inherit_box_label.setText(html)

    def set_auto_headers(self, rows: list[tuple[str, str, str]]) -> None:
        self._auto_rows = rows
        verb = "Hide" if self._show_auto else "Show"
        self._auto_toggle.setText(f"{verb} {len(rows)} auto-generated headers")
        if self._show_auto:
            self.auto_table.set_rows(rows)

    # ================================================================ edits
    def _edit(self, kind: str) -> None:
        if self._loading:
            return
        if kind == "params":
            self.request.params = self.params_table.rows()
        elif kind == "path_vars":
            self.request.path_vars = self.path_table.rows()
        elif kind == "headers":
            self.request.headers = self.headers_table.rows()
        elif kind == "body" and self.request.body_mode in ("form", "urlencoded"):
            self.request.form = self.form_table.rows()
        self._update_counts()
        self.edited.emit(kind)

    def _on_section(self, key: str) -> None:
        self.pages.setCurrentIndex([k for k, _ in SECTIONS].index(key))
        self.section_changed.emit(key)

    def _update_counts(self) -> None:
        r = self.request
        self.tabs.set_count("params", sum(1 for p in r.params if p.enabled and p.key))
        self.tabs.set_count("headers", sum(1 for h in r.headers if h.enabled and h.key))
        self.tabs.set_dot("body", r.body_mode != "none")

    def _toggle_bulk(self, table: KeyValueEditor, toggle) -> None:
        table.set_bulk(not table.is_bulk())
        toggle.setText("Key-value edit" if table.is_bulk() else "Bulk edit")

    def _toggle_auto(self) -> None:
        self._show_auto = not self._show_auto
        self.auto_table.setVisible(self._show_auto)
        manager().bind_icon(self._auto_toggle, "chevD" if self._show_auto else "chevR", "fg3", 12)
        self.set_auto_headers(self._auto_rows)

    # ------------------------------------------------------------- auth
    def _load_auth(self, auth: Auth) -> None:
        self.auth_type.set_text(AUTH_LABELS[auth.type])
        self.auth_pages.setCurrentIndex(AUTH_TYPES.index(auth.type))
        self.token.setText(auth.token)
        self.username.setText(auth.username)
        self.password.setText(auth.password)
        self.api_key.setText(auth.key)
        self.api_value.setText(auth.value)
        (self.add_query if auth.add_to == "query" else self.add_header).setChecked(True)

    def _open_auth_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self)
        for auth_type in AUTH_TYPES:
            menu.add_item(AUTH_LABELS[auth_type], lambda a=auth_type: self._set_auth_type(a),
                          checked=self.request.auth.type == auth_type)
        menu.show_at(anchor, width=anchor.width())

    def _set_auth_type(self, auth_type: str) -> None:
        self.request.auth.type = auth_type
        self.auth_type.set_text(AUTH_LABELS[auth_type])
        self.auth_pages.setCurrentIndex(AUTH_TYPES.index(auth_type))
        self.edited.emit("auth")

    def _sync_auth(self) -> None:
        if self._loading:
            return
        auth = self.request.auth
        auth.token, auth.username, auth.password = self.token.text(), self.username.text(), self.password.text()
        auth.key, auth.value = self.api_key.text(), self.api_value.text()
        auth.add_to = "query" if self.add_query.isChecked() else "header"
        self.edited.emit("auth")

    def _toggle_password(self) -> None:
        hidden = self.password.echoMode() == QLineEdit.EchoMode.Password
        self.password.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)

    # ------------------------------------------------------------- body
    def _set_body_mode(self, mode: str) -> None:
        if not self._loading and self.request.body_mode != mode:
            self.request.body_mode = mode
            self._show_body_page()
            self._update_counts()
            self.edited.emit("body")

    def _show_body_page(self) -> None:
        mode = self.request.body_mode
        self.body_pages.setCurrentIndex({"none": 0, "form": 1, "urlencoded": 1, "raw": 2}[mode])
        self.raw_type.setVisible(mode == "raw")
        self._beautify.setVisible(mode == "raw" and self.request.raw_type == "JSON")
        self._form_hint.setText("multipart/form-data" if mode == "form" else "application/x-www-form-urlencoded")
        self.form_table.set_files_enabled(mode == "form")

    def _open_raw_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self)
        for raw_type in RAW_TYPES:
            menu.add_item(raw_type, lambda r=raw_type: self._set_raw_type(r), checked=self.request.raw_type == raw_type)
        menu.show_at(anchor, width=150)

    def _set_raw_type(self, raw_type: str) -> None:
        self.request.raw_type = raw_type
        self.raw_type.set_text(raw_type)
        self.editor.set_language(raw_type)
        self._show_body_page()
        self.edited.emit("body")

    def _on_body_text(self) -> None:
        if self._loading:
            return
        self.request.body = self.editor.toPlainText()
        self.edited.emit("body")

    def set_body_text(self, text: str) -> None:
        """Replace the body (e.g. after Beautify) keeping undo history."""
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
