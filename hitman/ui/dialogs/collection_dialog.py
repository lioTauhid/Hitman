"""New collection / edit collection dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QLineEdit, QPushButton, QScrollArea, QStackedWidget, QWidget

from hitman.core.models import Auth, Collection
from hitman.ui.dialogs.base import OverlayDialog, accent_html
from hitman.ui.fonts import mono_font
from hitman.ui.theme import set_cls
from hitman.ui.widgets.common import CardButton, RoleLabel, button, hbox, label, vbox

AUTH_CHOICES = [
    ("none", "No auth", "Public endpoints"),
    ("bearer", "Bearer token", "JWT or opaque token"),
    ("basic", "Basic auth", "Username and password"),
    ("apikey", "API key", "Header or query param"),
]


@dataclass
class CollectionForm:
    name: str
    base_url: str
    auth: Auth


def _mono_input(text: str, placeholder: str) -> QLineEdit:
    edit = QLineEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.setAccessibleName(placeholder)
    edit.setProperty("mono", "true")
    edit.setFont(mono_font(12.5))
    edit.setFixedHeight(32)
    return edit


class CollectionDialog(OverlayDialog):
    """`result_form` is set on accept; `switch_to_import` is True if the user chose to import instead."""

    def __init__(self, parent: QWidget, collection: Collection | None = None):
        super().__init__(parent, 540, 630)
        self.result_form: CollectionForm | None = None
        self.switch_to_import = False
        editing = collection is not None
        auth = collection.auth if collection else Auth.with_variables("bearer")
        base_url = next((v.value for v in collection.variables if v.key == "baseUrl"), "") if collection else ""

        self.add_header("Edit collection" if editing else "New collection",
                        "Group related requests. They share auth and variables, and export together as one JSON file.",
                        icon="layers")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body_widget = QWidget()
        body = vbox(body_widget, (20, 18, 20, 18), 16)

        name_box = vbox(spacing=6)
        name_box.addWidget(label("Name", "section"))
        self.name = QLineEdit(collection.name if collection else "")
        set_cls(self.name, "dialog")
        self.name.setFixedHeight(36)
        self.name.setPlaceholderText("e.g. Orders API")
        self.name.textChanged.connect(lambda _t: self._sync())
        self.name.returnPressed.connect(self._submit)
        name_box.addWidget(self.name)
        body.addLayout(name_box)

        base_box = vbox(spacing=6)
        base_box.addWidget(label("Base URL", "section"))
        self.base = QLineEdit(base_url)
        set_cls(self.base, "dialog")
        self.base.setFixedHeight(36)
        self.base.setProperty("mono", "true")
        self.base.setFont(mono_font(12.5))
        self.base.setPlaceholderText("https://api.example.com/v1")
        self.base.returnPressed.connect(self._submit)
        base_box.addWidget(self.base)
        note = label("Saved as the collection variable " + accent_html("{{baseUrl}}") + " so every request can use it.",
                     "hint", wrap=True)
        note.setTextFormat(Qt.TextFormat.RichText)
        base_box.addWidget(note)
        body.addLayout(base_box)

        auth_box = vbox(spacing=8)
        auth_box.addWidget(label("Authorization", "section"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self._auth_group = QButtonGroup(self)
        self._auth_buttons: dict[str, QPushButton] = {}
        for i, (key, title, desc) in enumerate(AUTH_CHOICES):
            card = CardButton("option", title)
            card.setMinimumHeight(58)
            inner = vbox(card, (11, 9, 11, 9), 3)
            inner.addWidget(RoleLabel(title, "fg", px=12.5, weight=600))
            inner.addWidget(RoleLabel(desc, "fg3", px=11.5))
            card.finish()
            self._auth_group.addButton(card)
            self._auth_buttons[key] = card
            card.clicked.connect(lambda _c=False, k=key: self._pick_auth(k))
            grid.addWidget(card, i // 2, i % 2)
        auth_box.addLayout(grid)

        self._creds = QStackedWidget()
        self._creds.addWidget(QWidget())
        self.token = _mono_input(auth.token or "{{accessToken}}", "Token")
        self._creds.addWidget(self._labeled("Token", self.token))
        basic = QWidget()
        basic_row = hbox(basic, spacing=8)
        self.username = _mono_input(auth.username or "{{username}}", "Username")
        self.password = _mono_input(auth.password or "{{password}}", "Password")
        basic_row.addWidget(self._labeled("Username", self.username), 1)
        basic_row.addWidget(self._labeled("Password", self.password), 1)
        self._creds.addWidget(basic)
        api = QWidget()
        api_row = hbox(api, spacing=8)
        self.api_key = _mono_input(auth.key or "X-API-Key", "Key")
        self.api_value = _mono_input(auth.value or "{{apiKey}}", "Value")
        self.api_in = button("Header" if auth.add_to != "query" else "Query", height=32, on_click=self._flip_api_in)
        self.api_in.setToolTip("Where the key is sent")
        api_row.addWidget(self._labeled("Key", self.api_key), 1)
        api_row.addWidget(self._labeled("Value", self.api_value), 1)
        api_row.addWidget(self._labeled("Add to", self.api_in))
        self._creds.addWidget(api)
        auth_box.addWidget(self._creds)
        auth_box.addWidget(label("Requests inside the collection inherit this unless they set their own. "
                                 "Use {{variables}} to keep secrets in an environment.", "hint", wrap=True))
        body.addLayout(auth_box)
        body.addStretch(1)
        scroll.setWidget(body_widget)
        self.card_layout.addWidget(scroll, 1)

        hint = QWidget()
        if not editing:
            hint_row = hbox(hint, spacing=4)
            hint_row.addWidget(label("Have a file already?", "hint"))
            hint_row.addWidget(button("Import instead", "link", on_click=self._to_import))
            hint_row.addStretch(1)
        self.create_button = button("Save changes" if editing else "Create collection", "primary",
                                    height=34, on_click=self._submit)
        self.add_footer(hint, [self.cancel_button(self), self.create_button])
        self._pick_auth(auth.type if auth.type in self._auth_buttons else "none")
        self._sync()
        self.name.setFocus()

    @staticmethod
    def _labeled(caption: str, widget: QWidget) -> QWidget:
        box = QWidget()
        layout = vbox(box, spacing=4)
        layout.addWidget(label(caption, "small"))
        layout.addWidget(widget)
        return box

    def _pick_auth(self, key: str) -> None:
        self._auth_buttons[key].setChecked(True)
        self._creds.setCurrentIndex([k for k, _, _ in AUTH_CHOICES].index(key))
        self._creds.setVisible(key != "none")

    def _flip_api_in(self) -> None:
        self.api_in.setText("Query" if self.api_in.text() == "Header" else "Header")

    def _sync(self) -> None:
        self.create_button.setEnabled(bool(self.name.text().strip()))

    def _to_import(self) -> None:
        self.switch_to_import = True
        self.reject()

    def _auth(self) -> Auth:
        key = next(k for k, b in self._auth_buttons.items() if b.isChecked())
        return Auth(type=key, token=self.token.text().strip(), username=self.username.text().strip(),
                    password=self.password.text(), key=self.api_key.text().strip() or "X-API-Key",
                    value=self.api_value.text().strip(),
                    add_to="query" if self.api_in.text() == "Query" else "header")

    def _submit(self) -> None:
        name = self.name.text().strip()
        if not name:
            return
        self.result_form = CollectionForm(name=name, base_url=self.base.text().strip(), auth=self._auth())
        self.accept()
