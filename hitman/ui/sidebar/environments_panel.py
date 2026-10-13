"""Environments sidebar: pick the active environment and preview its variables."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QWidget

from hitman.core.models import Environment
from hitman.ui.dialogs.base import accent_html
from hitman.ui.theme import manager
from hitman.ui.widgets.common import (CardButton, ColorDot, IconButton, RoleLabel, button, clear_layout, hbox, label,
                                      vbox)
from hitman.ui.widgets.key_value import SimpleTable, caps_label

MASK = "••••••••••"


class _EnvRow(CardButton):
    def __init__(self, env: Environment, active: bool):
        super().__init__("row", env.name)
        self.setChecked(active)
        self.setFixedHeight(34)
        layout = hbox(self, (10, 0, 10, 0), 9)
        layout.addWidget(ColorDot(env.color, 8))
        name = RoleLabel(env.name, "fg", px=12.5, weight=600 if active else 400)
        layout.addWidget(name, 1)
        count = len(env.variables)
        layout.addWidget(RoleLabel(f"{count} var{'s' if count != 1 else ''}", "fg3", px=11))
        if active:
            check = RoleLabel("", "accent_text")
            manager().bind_icon(check, "check", "accent_text", 14, 2.2)
            layout.addWidget(check)
        self.finish()


class EnvironmentsPanel(QWidget):
    activate = Signal(str)          # environment id
    manage = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = vbox(self)
        header = QWidget()
        header.setFixedHeight(46)
        head = hbox(header, (16, 0, 8, 0), 4)
        head.addWidget(label("Environments", "panel-title"), 1)
        add = IconButton("plus", "New environment")
        add.clicked.connect(self.manage)
        head.addWidget(add)
        layout.addWidget(header)

        self._list = vbox(margins=(8, 0, 8, 0), spacing=1)
        layout.addLayout(self._list)

        title_row = hbox(margins=(16, 14, 16, 8), spacing=8)
        self._title = caps_label("Variables")
        title_row.addWidget(self._title, 1)
        title_row.addWidget(button("Manage", "link", on_click=self.manage.emit))
        layout.addLayout(title_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = vbox(body, (12, 0, 12, 16), 0)
        self._table = SimpleTable([("Key", 90), ("Value", 110)], header=False, mono=(True, True),
                                  roles=("fg2", "fg"), px=11.5, row_height=30, padding=9)
        self._empty = label("", "hint", wrap=True)
        body_layout.addWidget(self._table)
        body_layout.addWidget(self._empty)
        self._hint = label("", "small", wrap=True)
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setContentsMargins(2, 10, 2, 0)
        body_layout.addWidget(self._hint)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        manager().changed.connect(self._update_hint)
        self._update_hint()

    def _update_hint(self) -> None:
        self._hint.setText("Reference a variable anywhere in a request as " + accent_html("{{baseUrl}}") + ".")

    def set_environments(self, environments: list[Environment], active_id: str | None) -> None:
        clear_layout(self._list)
        for env in environments:
            row = _EnvRow(env, env.id == active_id)
            row.clicked.connect(lambda _c=False, e=env: self.manage.emit() if e.is_global else self.activate.emit(e.id))
            self._list.addWidget(row)
        active = next((e for e in environments if e.id == active_id), None)
        if active is None:
            self._title.setText("NO ENVIRONMENT")
            self._table.hide()
            self._empty.setText("Pick an environment above to point requests at it.")
            self._empty.show()
            return
        self._title.setText(f"{active.name} variables".upper())
        rows = [(v.key, (MASK if v.value else "—") if v.secret else (v.value or "—")) for v in active.variables if v.key]
        self._table.set_rows(rows)
        self._table.setVisible(bool(rows))
        self._empty.setText("This environment has no variables yet.")
        self._empty.setVisible(not rows)
