"""Manage environments: create, rename, color, activate and edit variables."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QFrame, QLabel, QLineEdit, QScrollArea,
                               QSizePolicy, QWidget)

from hitman.core.models import ENV_COLORS, Environment, Variable
from hitman.ui.dialogs.base import OverlayDialog, accent_html
from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.common import (CardButton, ColorDot, IconButton, RoleLabel, SearchField, SelectButton, button,
                                      clear_layout, hbox, label, separator, vbox)
from hitman.ui.widgets.popover import PopoverMenu

SWATCH_NAMES = {"ok": "Green", "warn": "Amber", "err": "Red", "put": "Blue", "patch": "Violet"}


class _Swatch(QAbstractButton):
    def __init__(self, token: str):
        super().__init__()
        self.token = token
        self.setCheckable(True)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(SWATCH_NAMES[token])
        self.setToolTip(SWATCH_NAMES[token])
        manager().changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isChecked():
            painter.setPen(QPen(t.c("fg2"), 2))
            painter.drawEllipse(QRectF(1, 1, 20, 20))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.env_color(self.token))
        painter.drawEllipse(QRectF(5, 5, 12, 12))


class _VarRow(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, var: Variable | None):
        super().__init__()
        self.ghost = var is None
        var = var or Variable()
        self._revealed = False
        set_cls(self, "table-row")
        self.setMinimumHeight(36)
        layout = hbox(self)
        check_cell = QWidget()
        check_cell.setFixedWidth(36)
        set_cls(check_cell, "cell")
        self.check = QCheckBox()
        self.check.setChecked(var.enabled)
        self.check.setVisible(not self.ghost)
        hbox(check_cell).addWidget(self.check, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(check_cell)

        self.key = QLineEdit(var.key)
        set_cls(self.key, "cell")
        self.key.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.key.setFont(mono_font(12))
        self.key.setPlaceholderText("Add a variable" if self.ghost else "")
        self.key.setAccessibleName("Variable name")
        layout.addWidget(self.key, 100)

        type_cell = QWidget()
        set_cls(type_cell, "cell")
        type_cell.setFixedWidth(100)
        self.secret = var.secret
        self.type_button = SelectButton("Secret" if var.secret else "Default", role="fg2", px=12, height=34,
                                        on_open=self._open_type_menu)
        self.type_button.setStyleSheet("QPushButton { background: transparent; border: 0; border-radius: 0; }")
        hbox(type_cell).addWidget(self.type_button)
        layout.addWidget(type_cell)

        self.value = QLineEdit(var.value)
        set_cls(self.value, "cell")
        self.value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.value.setFont(mono_font(12))
        self.value.setPlaceholderText("" if self.ghost else "Empty")
        self.value.setAccessibleName("Value")
        layout.addWidget(self.value, 160)

        actions = QWidget()
        actions.setFixedWidth(64)
        actions_layout = hbox(actions, (4, 0, 4, 0), 2)
        actions_layout.addStretch(1)
        self.reveal = IconButton("eye", "Show or hide value", size=(26, 26), icon_size=14, role="fg3", radius=6)
        self.reveal.clicked.connect(self._toggle_reveal)
        actions_layout.addWidget(self.reveal)
        self.delete = IconButton("trash", "Delete variable", size=(26, 26), icon_size=14, role="fg3", radius=6)
        self.delete.clicked.connect(lambda: self.removed.emit(self))
        self.delete.setVisible(not self.ghost)
        actions_layout.addWidget(self.delete)
        actions_layout.addStretch(1)
        layout.addWidget(actions)

        for edit in (self.key, self.value):
            edit.textEdited.connect(lambda _t: self.changed.emit())
        self.check.toggled.connect(self._on_toggle)
        manager().changed.connect(self._restyle)
        self._restyle()

    def _on_toggle(self, _on: bool) -> None:
        self._restyle()
        self.changed.emit()

    def materialize(self) -> None:
        self.ghost = False
        self.check.show()
        self.delete.show()
        self.key.setPlaceholderText("")
        self.value.setPlaceholderText("Empty")

    def _open_type_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self)
        menu.add_item("Default", lambda: self._set_secret(False), checked=not self.secret)
        menu.add_item("Secret", lambda: self._set_secret(True), checked=self.secret)
        menu.show_at(anchor, width=130)

    def _set_secret(self, secret: bool) -> None:
        self.secret = secret
        self.type_button.set_text("Secret" if secret else "Default")
        self._restyle()
        self.changed.emit()

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._restyle()

    def _restyle(self) -> None:
        t = theme()
        dim = not self.check.isChecked() and not self.ghost
        color = t.c("fg3" if dim else "fg").name()
        self.key.setStyleSheet(f"padding: 0 10px; color: {color};")
        self.value.setStyleSheet(f"padding: 0 10px; color: {color};")
        hidden = self.secret and not self._revealed
        self.value.setEchoMode(QLineEdit.EchoMode.Password if hidden else QLineEdit.EchoMode.Normal)
        self.reveal.setVisible(self.secret)

    def variable(self) -> Variable:
        return Variable(key=self.key.text().strip(), value=self.value.text(), enabled=self.check.isChecked(),
                        secret=self.secret)


class _EnvItem(CardButton):
    def __init__(self, env: Environment, selected: bool, active: bool):
        super().__init__("nav-accent", env.name)
        self.setChecked(selected)
        self.setMinimumHeight(40)
        layout = hbox(self, (10, 4, 10, 4), 10)
        layout.addWidget(ColorDot(env.color, 9))
        text = vbox(spacing=0)
        text.addWidget(RoleLabel(env.name, "fg", px=12.5, weight=600 if selected else 500))
        count = len(env.variables)
        meta = f"Always applied · {count} vars" if env.is_global else f"{count} variable{'s' if count != 1 else ''}"
        text.addWidget(RoleLabel(meta, "fg3", px=11))
        layout.addLayout(text, 1)
        if active:
            layout.addWidget(set_cls(QLabel("Active"), "badge"))
        self.finish()


class EnvironmentsDialog(OverlayDialog):
    """Edits a copy; on accept read `environments` and `active_id`."""

    def __init__(self, parent: QWidget, environments: list[Environment], active_id: str | None,
                 select_id: str | None = None, create: bool = False):
        super().__init__(parent, 900, 600)
        self.environments = [e.copy() for e in environments]
        self.active_id = active_id
        regular = [e for e in self.environments if not e.is_global]
        self._sel = select_id or active_id or (regular[0].id if regular else self.environments[0].id)
        self._var_rows: list[_VarRow] = []

        subtitle = ("Reference a variable as " + accent_html("{{baseUrl}}") + " in URLs, headers and bodies. "
                    "Switch environments to point every request somewhere else.")
        self.add_header("Environments", subtitle)
        content = hbox()
        side = QFrame()
        set_cls(side, "side-panel-bl")
        side.setFixedWidth(250)
        side_layout = vbox(side)
        search_box = vbox(margins=(12, 12, 12, 8))
        self.search = SearchField("Search", height=32, strong=True)
        self.search.edit.textChanged.connect(lambda _t: self._render_list())
        search_box.addWidget(self.search)
        side_layout.addLayout(search_box)
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_body = QWidget()
        self._list = vbox(list_body, (8, 0, 8, 8), 2)
        list_scroll.setWidget(list_body)
        side_layout.addWidget(list_scroll, 1)
        add_box = QWidget()
        add_layout = vbox(add_box, (8, 8, 8, 8))
        add_layout.addWidget(button("New environment", "dashed", icon="plus", icon_size=14, height=32,
                                    on_click=self._add_env))
        side_layout.addWidget(separator(vertical=False))
        side_layout.addWidget(add_box)
        content.addWidget(side)

        right = vbox()
        head = hbox(margins=(20, 14, 16, 12), spacing=10)
        self.name = QLineEdit()
        set_cls(self.name, "title")
        self.name.setFixedHeight(34)
        self.name.setAccessibleName("Environment name")
        self.name.textEdited.connect(self._rename)
        head.addWidget(self.name, 1)
        swatches = hbox(spacing=4)
        self._swatch_group = QButtonGroup(self)
        self._swatches: dict[str, _Swatch] = {}
        for token in ENV_COLORS:
            swatch = _Swatch(token)
            self._swatch_group.addButton(swatch)
            swatch.clicked.connect(lambda _c=False, tok=token: self._recolor(tok))
            self._swatches[token] = swatch
            swatches.addWidget(swatch)
        self._swatch_box = QWidget()
        self._swatch_box.setLayout(swatches)
        head.addWidget(self._swatch_box)
        self.activate_button = button("Set as active", height=30, on_click=self._activate)
        head.addWidget(self.activate_button)
        self.global_note = label("Applied in every environment", "hint")
        head.addWidget(self.global_note)
        dup = IconButton("copy", "Duplicate environment", size=(30, 30), icon_size=15)
        dup.clicked.connect(self._duplicate)
        head.addWidget(dup)
        self.delete_button = IconButton("trash", "Delete environment", size=(30, 30), icon_size=15, role="err")
        self.delete_button.clicked.connect(self._delete)
        head.addWidget(self.delete_button)
        right.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        vars_body = QWidget()
        vars_layout = vbox(vars_body, (20, 0, 20, 14), 0)
        table = QFrame()
        set_cls(table, "table")
        table_layout = vbox(table)
        table_layout.addWidget(self._table_head())
        self._rows_layout = vbox()
        table_layout.addLayout(self._rows_layout)
        vars_layout.addWidget(table)
        note = label("Values are stored on this machine. Mark tokens and passwords as <b>Secret</b> to mask them "
                     "and keep them out of exports.", "hint", wrap=True)
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setContentsMargins(0, 12, 0, 0)
        vars_layout.addWidget(note)
        vars_layout.addStretch(1)
        scroll.setWidget(vars_body)
        right.addWidget(scroll, 1)
        content.addLayout(right, 1)
        self.card_layout.addLayout(content, 1)

        self.summary = label("", "hint")
        save = button("Save changes", "primary", height=34, on_click=self._save)
        self.add_footer(self.summary, [self.cancel_button(self), save])
        if create:
            self._add_env()
        else:
            self._render()

    @staticmethod
    def _table_head() -> QFrame:
        head = QFrame()
        set_cls(head, "table-head")
        head.setFixedHeight(32)
        layout = hbox(head)
        spacer = QWidget()
        spacer.setFixedWidth(36)
        layout.addWidget(spacer)
        layout.addWidget(set_cls(QLabel("Variable"), "cell-head"), 100)
        type_label = set_cls(QLabel("Type"), "cell-head")
        type_label.setFixedWidth(100)
        layout.addWidget(type_label)
        layout.addWidget(set_cls(QLabel("Value"), "cell-head"), 160)
        tail = QWidget()
        tail.setFixedWidth(64)
        layout.addWidget(tail)
        return head

    # ------------------------------------------------------------ render
    def _current(self) -> Environment:
        return next((e for e in self.environments if e.id == self._sel), self.environments[0])

    def _render(self) -> None:
        self._render_list()
        env = self._current()
        self.name.setText(env.name)
        self.name.setReadOnly(env.is_global)
        self._swatch_box.setVisible(not env.is_global)
        if env.color in self._swatches:
            self._swatches[env.color].setChecked(True)
        self.activate_button.setVisible(not env.is_global and env.id != self.active_id)
        self.global_note.setVisible(env.is_global)
        self.delete_button.setEnabled(not env.is_global)
        clear_layout(self._rows_layout)
        self._var_rows = []
        for var in env.variables:
            self._add_var_row(var)
        self._add_var_row(None)
        self._update_summary()

    def _render_list(self) -> None:
        clear_layout(self._list)
        q = self.search.text().strip().lower()
        for env in self.environments:
            if q and q not in env.name.lower():
                continue
            item = _EnvItem(env, env.id == self._sel, env.id == self.active_id)
            item.clicked.connect(lambda _c=False, e=env.id: self._select(e))
            self._list.addWidget(item)
        self._list.addStretch(1)

    def _add_var_row(self, var: Variable | None) -> None:
        row = _VarRow(var)
        row.changed.connect(lambda r=row: self._on_var_changed(r))
        row.removed.connect(self._on_var_removed)
        self._var_rows.append(row)
        self._rows_layout.addWidget(row)

    # ------------------------------------------------------------ edits
    def _sync_vars(self) -> None:
        self._current().variables = [r.variable() for r in self._var_rows if not r.ghost]
        self._update_summary()

    def _on_var_changed(self, row: _VarRow) -> None:
        if row.ghost:
            row.materialize()
            self._add_var_row(None)
        self._sync_vars()
        self._render_list()

    def _on_var_removed(self, row: _VarRow) -> None:
        self._var_rows.remove(row)
        row.deleteLater()
        self._sync_vars()
        self._render_list()

    def _select(self, env_id: str) -> None:
        self._sync_vars()
        self._sel = env_id
        self._render()

    def _rename(self, text: str) -> None:
        env = self._current()
        if not env.is_global:
            env.name = text
            self._render_list()

    def _recolor(self, token: str) -> None:
        self._current().color = token
        self._render_list()

    def _activate(self) -> None:
        self.active_id = self._sel
        self._render()

    def _add_env(self) -> None:
        if self._var_rows:
            self._sync_vars()
        env = Environment(name="New environment", color="put", variables=[Variable(key="baseUrl")])
        self.environments.append(env)
        self._sel = env.id
        self._render()
        self.name.setFocus()
        self.name.selectAll()

    def _duplicate(self) -> None:
        self._sync_vars()
        source = self._current()
        copy = source.copy()
        copy.id = Environment().id
        copy.name = f"{source.name} copy"
        copy.is_global = False
        if copy.color not in ENV_COLORS:
            copy.color = "put"
        self.environments.append(copy)
        self._sel = copy.id
        self._render()

    def _delete(self) -> None:
        env = self._current()
        if env.is_global:
            return
        self.environments.remove(env)
        fallback = next((e for e in self.environments if not e.is_global), self.environments[0])
        if self.active_id == env.id:
            self.active_id = fallback.id if not fallback.is_global else None
        self._sel = fallback.id
        self._render()

    def _update_summary(self) -> None:
        total = sum(len(e.variables) for e in self.environments)
        secrets = sum(1 for e in self.environments for v in e.variables if v.secret)
        count = len(self.environments)
        self.summary.setText(f"{count} environment{'s' if count != 1 else ''} · {total} variables · {secrets} secret")

    def _save(self) -> None:
        self._sync_vars()
        for env in self.environments:
            env.name = env.name.strip() or "Untitled environment"
            env.variables = [v for v in env.variables if v.key]
        self.accept()
