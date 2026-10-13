"""Save request dialog: name the request and choose its collection or folder."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QScrollArea, QWidget

from hitman.core.models import Collection, iter_folders
from hitman.ui.dialogs.base import OverlayDialog
from hitman.ui.theme import manager, set_cls
from hitman.ui.widgets.common import (CardButton, ElidedLabel, RoleLabel, SearchField, button, clear_layout, hbox, label,
                                      separator, vbox)

PENDING = "__pending__"


@dataclass
class SaveTarget:
    name: str
    collection_id: str | None          # None when a new collection should be created
    folder_id: str | None              # parent folder; None for the collection root
    new_collection: str | None = None  # name of a collection to create first
    new_folder: str | None = None      # name of a folder to create inside folder_id/collection


class SaveRequestDialog(OverlayDialog):
    def __init__(self, parent: QWidget, collections: list[Collection], request_name: str, *,
                 save_as: bool = False, collection_id: str | None = None, folder_id: str | None = None):
        super().__init__(parent, 560, 500)
        self.result_target: SaveTarget | None = None
        self._collections = collections
        self._new_collection: str | None = None
        self._new_folder: tuple[str, str | None, str] | None = None  # (collection_id, parent_folder_id, name)
        first = collections[0].id if collections else None
        self._sel_col = collection_id if any(c.id == collection_id for c in collections) else first
        self._sel_folder = folder_id if collection_id == self._sel_col else None
        self._open = {self._sel_col} if self._sel_col else set()

        self.add_header("Save as" if save_as else "Save request",
                        "Name the request and pick the collection or folder it belongs to.")
        body = vbox(margins=(20, 16, 20, 16), spacing=14)
        name_box = vbox(spacing=6)
        name_box.addWidget(label("Request name", "section"))
        self.name = QLineEdit(request_name)
        set_cls(self.name, "dialog")
        self.name.setFixedHeight(36)
        self.name.setPlaceholderText("e.g. Get user")
        self.name.textChanged.connect(lambda _t: self._sync_footer())
        self.name.returnPressed.connect(self._save)
        name_box.addWidget(self.name)
        body.addLayout(name_box)

        where_row = hbox(spacing=8)
        where_row.addWidget(label("Save to", "section"))
        self.where = ElidedLabel("", "fg3", px=12)
        where_row.addWidget(self.where, 1)
        body.addLayout(where_row)

        box = QFrame()
        set_cls(box, "note")
        box.setMinimumHeight(150)
        box_layout = vbox(box)
        self.search = SearchField("Search collections and folders", height=36)
        self.search.setStyleSheet("QFrame { background: transparent; border: 0; border-radius: 0; }")
        self.search.edit.textChanged.connect(lambda _t: self._render())
        box_layout.addWidget(self.search)
        box_layout.addWidget(separator(vertical=False))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self._rows = vbox(inner, (6, 6, 6, 6), 0)
        scroll.setWidget(inner)
        box_layout.addWidget(scroll, 1)
        box_layout.addWidget(separator(vertical=False))

        footer = hbox(margins=(6, 6, 6, 6), spacing=6)
        self.new_button = button("", "link", icon="plus", icon_role="accent_text", icon_size=13,
                                 on_click=self._start_new)
        self.new_button.setStyleSheet("padding: 0 10px; min-height: 28px;")
        footer.addWidget(self.new_button)
        self.new_input = QLineEdit()
        self.new_input.setFixedHeight(28)
        self.new_input.returnPressed.connect(self._commit_new)
        self.new_input.hide()
        footer.addWidget(self.new_input, 1)
        self.new_add = button("Add", height=28, on_click=self._commit_new)
        self.new_add.hide()
        footer.addWidget(self.new_add)
        footer.addStretch(0)
        box_layout.addLayout(footer)
        body.addWidget(box, 1)
        self.card_layout.addLayout(body, 1)

        mod = "⌘S" if sys.platform == "darwin" else "Ctrl+S"
        hint = label(f"Shortcut <span style=\"font-family:'Geist Mono',monospace\">{mod}</span>", "hint")
        hint.setTextFormat(Qt.TextFormat.RichText)
        self.save_button = button("Save", "primary", height=34, on_click=self._save)
        self.add_footer(hint, [self.cancel_button(self), self.save_button])
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(self._save)
        self._render()
        self.name.setFocus()
        self.name.selectAll()

    # --------------------------------------------------------------- rows
    def _entries(self) -> list[tuple[str, str, str, str | None, int]]:
        """(kind, collection_id, name, folder_id, depth) for collections and folders, incl. pending ones."""
        out = []
        for col in self._collections:
            out.append(("collection", col.id, col.name, None, 0))
            for folder, depth in iter_folders(col.items):
                out.append(("folder", col.id, folder.name, folder.id, depth + 1))
                if self._new_folder and self._new_folder[0] == col.id and self._new_folder[1] == folder.id:
                    out.append(("folder", col.id, self._new_folder[2], PENDING, depth + 2))
            if self._new_folder and self._new_folder[0] == col.id and self._new_folder[1] is None:
                out.append(("folder", col.id, self._new_folder[2], PENDING, 1))
        if self._new_collection:
            out.append(("collection", PENDING, self._new_collection, None, 0))
        return out

    def _render(self) -> None:
        clear_layout(self._rows)
        q = self.search.text().strip().lower()
        entries = self._entries()
        shown = 0
        for kind, col_id, name, folder_id, depth in entries:
            col_name = next((n for k, c, n, _f, _d in entries if k == "collection" and c == col_id), "")
            if q and q not in name.lower() and q not in col_name.lower():
                continue
            if kind == "folder" and not q and col_id not in self._open:
                continue
            selected = (kind == "collection" and self._sel_col == col_id and not self._sel_folder) or \
                       (kind == "folder" and self._sel_folder == folder_id and self._sel_col == col_id)
            self._rows.addWidget(self._row(kind, col_id, name, folder_id, depth, selected))
            shown += 1
        if not shown:
            text = f"No collection or folder matches “{q}”." if q else "No collections yet. Create one below."
            empty = label(text, "muted", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(20, 20, 20, 20)
            self._rows.addWidget(empty)
        self._rows.addStretch(1)
        self._sync_footer()

    def _row(self, kind: str, col_id: str, name: str, folder_id: str | None, depth: int, selected: bool) -> CardButton:
        row = CardButton("row", name)
        row.setChecked(selected)
        row.setFixedHeight(32)
        layout = hbox(row, (10 if kind == "collection" else 40 + (depth - 1) * 14, 0, 10, 0), 8)
        if kind == "collection":
            chevron = QLabel()
            manager().bind_icon(chevron, "chevD" if col_id in self._open else "chevR", "fg3", 11, 2.4)
            layout.addWidget(chevron)
            icon = QLabel()
            manager().bind_icon(icon, "layers", "fg2", 15)
        else:
            icon = QLabel()
            manager().bind_icon(icon, "folder", "fg3", 15)
        layout.addWidget(icon)
        layout.addWidget(RoleLabel(name, "fg", px=12.5, weight=600 if kind == "collection" else 400), 1)
        if selected:
            check = QLabel()
            manager().bind_icon(check, "check", "accent_text", 14, 2.4)
            layout.addWidget(check)
        row.finish()
        row.clicked.connect(lambda _c=False: self._pick(kind, col_id, folder_id))
        return row

    def _pick(self, kind: str, col_id: str, folder_id: str | None) -> None:
        if kind == "collection":
            if self._sel_col == col_id and not self._sel_folder:
                self._open.symmetric_difference_update({col_id})
            else:
                self._open.add(col_id)
            self._sel_col, self._sel_folder = col_id, None
        else:
            self._sel_col, self._sel_folder = col_id, folder_id
        self._render()

    # --------------------------------------------------------- new items
    def _selection_name(self) -> str:
        for kind, col_id, name, folder_id, _depth in self._entries():
            if col_id == self._sel_col and ((kind == "folder" and folder_id == self._sel_folder) or
                                            (kind == "collection" and not self._sel_folder)):
                return name
        return ""

    def _start_new(self) -> None:
        self.new_button.hide()
        self.new_input.setPlaceholderText("Folder name" if self._sel_col else "Collection name")
        self.new_input.clear()
        self.new_input.show()
        self.new_add.show()
        self.new_input.setFocus()

    def _commit_new(self) -> None:
        name = self.new_input.text().strip()
        self.new_input.hide()
        self.new_add.hide()
        self.new_button.show()
        if not name:
            return
        if self._sel_col:
            if self._sel_folder == PENDING:
                return  # one pending folder at a time
            self._new_folder = (self._sel_col, self._sel_folder, name)
            self._sel_folder = PENDING
            self._open.add(self._sel_col)
        else:
            self._new_collection = name
            self._sel_col, self._sel_folder = PENDING, None
        self._render()

    # ------------------------------------------------------------- footer
    def _sync_footer(self) -> None:
        target = self._selection_name()
        crumbs = [self._selection_collection_name()] + ([target] if self._sel_folder else [])
        self.where.setText(" / ".join(c for c in crumbs if c) or "Pick a location")
        self.save_button.setText(f"Save to {target}" if target else "Save")
        self.save_button.setEnabled(bool(self.name.text().strip()) and bool(self._sel_col))
        can_folder = bool(self._sel_col) and self._sel_folder != PENDING
        self.new_button.setText(f"New folder in {target}" if can_folder else "New collection")
        self.new_button.setVisible(not self.new_input.isVisible() and (can_folder or not self._collections
                                                                        and not self._new_collection))

    def _selection_collection_name(self) -> str:
        if self._sel_col == PENDING:
            return self._new_collection or ""
        return next((c.name for c in self._collections if c.id == self._sel_col), "")

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name or not self._sel_col:
            return
        new_folder = self._new_folder[2] if self._sel_folder == PENDING and self._new_folder else None
        parent_folder = self._new_folder[1] if new_folder else self._sel_folder
        self.result_target = SaveTarget(
            name=name,
            collection_id=None if self._sel_col == PENDING else self._sel_col,
            folder_id=parent_folder,
            new_collection=self._new_collection if self._sel_col == PENDING else None,
            new_folder=new_folder,
        )
        self.accept()
