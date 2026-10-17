"""Editable key/value tables (params, headers, form fields, path variables) and read-only tables."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QFrame, QLabel, QLineEdit, QPlainTextEdit, QSizePolicy, QStackedWidget,
                               QWidget)

from hitman.core.models import KeyValue
from hitman.ui.fonts import mono_font, ui_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.common import ElidedLabel, IconButton, SelectButton, hbox, vbox
from hitman.ui.widgets.file_field import FileField
from hitman.ui.widgets.popover import PopoverMenu

# Column stretch factors from the design: Key 1fr, Value 1.25fr, Description 1.1fr.
_STRETCH = (100, 125, 110)


def _cell_edit(placeholder: str, mono: bool, last: bool = False) -> QLineEdit:
    edit = QLineEdit()
    set_cls(edit, "bare" if last else "cell")
    edit.setPlaceholderText(placeholder)
    edit.setAccessibleName(placeholder)
    edit.setFont(mono_font(12) if mono else ui_font(12.5))
    edit.setStyleSheet("padding: 0 10px;")
    edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return edit


class _Row(QFrame):
    edited = Signal(object)
    removed = Signal(object)

    def __init__(self, *, ghost: bool, fixed_key: bool, show_description: bool, first: bool,
                 key_placeholder: str, value_placeholder: str, allow_files: bool = False):
        super().__init__()
        self.ghost, self.fixed_key, self.allow_files = ghost, fixed_key, allow_files
        self.type = "text"
        set_cls(self, "table-row-first" if first else "table-row")
        self.setMinimumHeight(34)
        layout = hbox(self)

        self.check_cell = QWidget()
        self.check_cell.setFixedWidth(36)
        if not fixed_key:
            set_cls(self.check_cell, "cell")
        cell_layout = hbox(self.check_cell)
        self.check = QCheckBox()
        self.check.setChecked(True)
        cell_layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.check_cell)

        self.key = _cell_edit(key_placeholder, mono=True, last=allow_files)
        self.value = _cell_edit(value_placeholder, mono=True, last=allow_files or not show_description)
        self.type_button: SelectButton | None = None
        self.file_field: FileField | None = None
        if allow_files:
            layout.addWidget(self._build_key_cell(), _STRETCH[0])
            layout.addWidget(self._build_value_cell(show_description), _STRETCH[1])
        else:
            layout.addWidget(self.key, _STRETCH[0])
            layout.addWidget(self.value, _STRETCH[1])
        self.description = None
        if show_description:
            self.description = _cell_edit("Description" if ghost else "", mono=False, last=True)
            layout.addWidget(self.description, _STRETCH[2])

        if fixed_key:
            self.key.setReadOnly(True)
            self.key.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.check.hide()
        self.delete_cell = QWidget()
        self.delete_cell.setFixedWidth(0 if fixed_key else 34)
        delete_layout = hbox(self.delete_cell)
        self.delete = IconButton("trash", "Remove", size=(24, 24), icon_size=14, role="fg3", radius=6)
        delete_layout.addWidget(self.delete, 0, Qt.AlignmentFlag.AlignCenter)
        policy = self.delete.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.delete.setSizePolicy(policy)
        self.delete.hide()
        layout.addWidget(self.delete_cell)

        self.check.setVisible(not ghost and not fixed_key)
        for edit in self._edits():
            edit.textEdited.connect(lambda _t: self.edited.emit(self))
        self.check.toggled.connect(self._on_toggle)
        self.delete.clicked.connect(lambda: self.removed.emit(self))
        manager().changed.connect(self._restyle)
        self._restyle()

    # ------------------------------------------------------- file fields
    def _build_key_cell(self) -> QFrame:
        """Key input plus a Text/File type picker."""
        cell = QFrame()
        set_cls(cell, "cell")
        layout = hbox(cell, (0, 0, 4, 0), 2)
        layout.addWidget(self.key, 1)
        self.type_button = SelectButton("Text", px=11.5, role="fg3", height=22, margins=(7, 0, 5, 0),
                                        on_open=self._open_type_menu)
        self.type_button.setObjectName("FieldType")
        self.type_button.setFixedWidth(60)
        self.type_button.setToolTip("Send this field as text or as a file")
        self.type_button.setAccessibleName("Field type: Text")
        layout.addWidget(self.type_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return cell

    def _build_value_cell(self, bordered: bool) -> QFrame:
        """Text input or file picker, depending on the field type."""
        cell = QFrame()
        if bordered:
            set_cls(cell, "cell")
        self.value_stack = QStackedWidget()
        self.value_stack.addWidget(self.value)
        self.file_field = FileField()
        self.file_field.changed.connect(lambda: self.edited.emit(self))
        self.value_stack.addWidget(self.file_field)
        hbox(cell).addWidget(self.value_stack)
        return cell

    def _open_type_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self)
        menu.add_item("Text", lambda: self.set_type("text", user=True), checked=self.type == "text")
        menu.add_item("File", lambda: self.set_type("file", user=True), checked=self.type == "file")
        menu.show_at(anchor, width=120)

    def set_type(self, field_type: str, user: bool = False) -> None:
        if not self.allow_files:
            return
        changed = field_type != self.type
        self.type = field_type
        label = "File" if field_type == "file" else "Text"
        self.type_button.set_text(label)
        self.type_button.setAccessibleName(f"Field type: {label}")
        self.value_stack.setCurrentIndex(1 if field_type == "file" else 0)
        self._restyle()
        if user and changed:
            self.edited.emit(self)

    def set_files_enabled(self, enabled: bool) -> None:
        if self.allow_files:
            self.type_button.setVisible(enabled)
            self.file_field.set_files_enabled(enabled)

    def _edits(self) -> list[QLineEdit]:
        return [e for e in (self.key, self.value, self.description) if e is not None]

    def _on_toggle(self, _on: bool) -> None:
        self._restyle()
        self.edited.emit(self)

    def _restyle(self) -> None:
        t = theme()
        dim = not self.check.isChecked() and not self.ghost
        key_role = "patch" if self.fixed_key else ("fg3" if dim else "fg")
        self.key.setStyleSheet(f"padding: 0 10px 0 {46 - 36 if self.fixed_key else 10}px; color: {t.c(key_role).name()};")
        self.value.setStyleSheet(f"padding: 0 10px; color: {t.c('fg3' if dim else 'fg').name()};")
        if self.description:
            self.description.setStyleSheet(f"padding: 0 10px; color: {t.c('fg3' if dim else 'fg2').name()};")
        if self.file_field:
            self.file_field.set_dim(dim)

    def materialize(self) -> None:
        self.ghost = False
        self.check.show()
        if self.description:
            self.description.setPlaceholderText("")

    def enterEvent(self, event) -> None:  # noqa: N802
        if not self.ghost and not self.fixed_key:
            self.delete.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.delete.hide()
        super().leaveEvent(event)

    def set_data(self, row: KeyValue) -> None:
        key = f":{row.key}" if self.fixed_key else row.key
        file_row = self.allow_files and row.is_file
        for edit, text in ((self.key, key), (self.value, "" if file_row else row.value)):
            if edit.text() != text:
                edit.setText(text)
        if self.allow_files:
            self.file_field.set_path(row.value if file_row else "")
            self.set_type("file" if file_row else "text")
        if self.description and self.description.text() != row.description:
            self.description.setText(row.description)
        self.check.blockSignals(True)
        self.check.setChecked(row.enabled)
        self.check.blockSignals(False)
        self._restyle()

    def data(self) -> KeyValue:
        key = self.key.text().removeprefix(":") if self.fixed_key else self.key.text()
        is_file = self.allow_files and self.type == "file"
        return KeyValue(key=key, value=self.file_field.path() if is_file else self.value.text(),
                        description=self.description.text() if self.description else "",
                        enabled=self.check.isChecked() or self.fixed_key, type="file" if is_file else "text")


class KeyValueEditor(QWidget):
    """Table of key/value rows with a trailing "ghost" row for adding entries, plus bulk edit."""

    changed = Signal()

    def __init__(self, *, show_description: bool = True, fixed_keys: bool = False, header: bool = True,
                 key_placeholder: str = "Key", value_placeholder: str = "Value", allow_files: bool = False,
                 parent: QWidget | None = None):
        """`allow_files` adds a Text/File picker to each row (for multipart form-data bodies)."""
        super().__init__(parent)
        self._show_description = show_description
        self._fixed = fixed_keys
        self._allow_files = allow_files
        self._files_enabled = True
        self._types: dict[str, str] = {}  # remembers file fields across bulk edits
        self._key_ph, self._value_ph = key_placeholder, value_placeholder
        self._rows: list[_Row] = []
        self._descriptions: dict[str, str] = {}
        self._has_header = header
        self._bulk = False

        layout = vbox(self)
        self.table = QFrame()
        set_cls(self.table, "table")
        self._table_layout = vbox(self.table)
        if header:
            self._table_layout.addWidget(self._header())
        self._rows_layout = vbox()
        self._table_layout.addLayout(self._rows_layout)
        layout.addWidget(self.table)

        self.bulk = QPlainTextEdit()
        self.bulk.setProperty("mono", "true")
        self.bulk.setFont(mono_font(12))
        self.bulk.setPlaceholderText(f"{key_placeholder}: {value_placeholder}\n// Prefix a line with // to disable it")
        self.bulk.setMinimumHeight(140)
        self.bulk.hide()
        self.bulk.textChanged.connect(self._on_bulk_text)
        layout.addWidget(self.bulk)
        if not fixed_keys:
            self._add_row(ghost=True)

    def _header(self) -> QFrame:
        head = QFrame()
        set_cls(head, "table-head")
        head.setFixedHeight(30)
        layout = hbox(head)
        spacer = QWidget()
        spacer.setFixedWidth(36)
        layout.addWidget(spacer)
        names = ["Key", "Value"] + (["Description"] if self._show_description else [])
        for name, stretch in zip(names, _STRETCH):
            layout.addWidget(set_cls(QLabel(name), "cell-head"), stretch)
        tail = QWidget()
        tail.setFixedWidth(34)
        layout.addWidget(tail)
        return head

    # -------------------------------------------------------------- rows
    def _add_row(self, ghost: bool) -> _Row:
        row = _Row(ghost=ghost, fixed_key=self._fixed, show_description=self._show_description, first=False,
                   key_placeholder=self._key_ph if not self._fixed else "", value_placeholder=self._value_ph,
                   allow_files=self._allow_files)
        row.set_files_enabled(self._files_enabled)
        row.edited.connect(self._on_row_edited)
        row.removed.connect(self._on_row_removed)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._restripe()
        return row

    def _restripe(self) -> None:
        """Rows draw a top border, except the very first one when there is no header."""
        for index, row in enumerate(self._rows):
            cls = "table-row-first" if index == 0 and not self._has_header else "table-row"
            if row.property("cls") != cls:
                set_cls(row, cls)

    def _on_row_edited(self, row: _Row) -> None:
        if row.ghost:
            row.materialize()
            self._add_row(ghost=True)
        self.changed.emit()

    def _on_row_removed(self, row: _Row) -> None:
        self._rows.remove(row)
        row.deleteLater()
        self._restripe()
        self.changed.emit()

    def set_rows(self, rows: list[KeyValue]) -> None:
        """Show `rows` without emitting `changed`. Reuses row widgets to keep focus stable."""
        real = [r for r in self._rows if not r.ghost]
        while len(real) > len(rows):
            row = real.pop()
            self._rows.remove(row)
            row.deleteLater()
        ghost = next((r for r in self._rows if r.ghost), None)
        while len(real) < len(rows):
            row = self._add_row(ghost=False)
            real.append(row)
        if ghost:  # keep the ghost row last
            self._rows.remove(ghost)
            self._rows_layout.removeWidget(ghost)
            self._rows.append(ghost)
            self._rows_layout.addWidget(ghost)
        for row_widget, data in zip(real, rows):
            row_widget.set_data(data)
        self._restripe()
        self._remember(rows)
        if self._bulk:
            self._fill_bulk(rows)

    def set_files_enabled(self, enabled: bool) -> None:
        """Show the Text/File pickers (form-data) or hide them (url-encoded, where files aren't sent)."""
        self._files_enabled = enabled
        for row in self._rows:
            row.set_files_enabled(enabled)

    def _remember(self, rows: list[KeyValue]) -> None:
        """Bulk edit only shows `key: value`; keep descriptions and file types to restore afterwards."""
        self._descriptions = {r.key: r.description for r in rows if r.description}
        self._types = {r.key: r.type for r in rows if r.is_file}

    def rows(self) -> list[KeyValue]:
        if self._bulk:
            return self._parse_bulk()
        return [r.data() for r in self._rows if not r.ghost]

    # -------------------------------------------------------------- bulk
    def is_bulk(self) -> bool:
        return self._bulk

    def set_bulk(self, on: bool) -> None:
        if on == self._bulk:
            return
        if on:
            rows = self.rows()
            self._remember(rows)
            self._fill_bulk(rows)
            self._bulk = True
            self.table.hide()
            self.bulk.show()
            self.bulk.setFocus()
        else:
            rows = self._parse_bulk()
            self._bulk = False
            self.bulk.hide()
            self.table.show()
            self.set_rows(rows)

    def _fill_bulk(self, rows: list[KeyValue]) -> None:
        text = "\n".join(("" if r.enabled else "//") + f"{r.key}: {r.value}" for r in rows)
        self.bulk.blockSignals(True)
        self.bulk.setPlainText(text)
        self.bulk.blockSignals(False)

    def _parse_bulk(self) -> list[KeyValue]:
        out = []
        for line in self.bulk.toPlainText().splitlines():
            if not line.strip():
                continue
            enabled = not line.lstrip().startswith("//")
            body = line.lstrip()[2:] if not enabled else line
            key, sep, value = body.partition(":")
            if not sep:
                key, _, value = body.partition("=")
            key = key.strip()
            out.append(KeyValue(key=key, value=value.strip(), description=self._descriptions.get(key, ""),
                                enabled=enabled, type=self._types.get(key, "text")))
        return out

    def _on_bulk_text(self) -> None:
        self.changed.emit()


class SimpleTable(QFrame):
    """Read-only grid of elided labels with an optional header row."""

    def __init__(self, columns: list[tuple[str, int]], *, header: bool = True, mono: tuple[bool, ...] = (),
                 roles: tuple[str, ...] = (), px: float = 12, row_height: int = 32, padding: int = 10,
                 lead_icon: str | None = None, muted: bool = False, column_lines: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        set_cls(self, "table-flat")
        self._columns, self._mono, self._roles = columns, mono, roles
        self._px, self._row_height, self._padding = px, row_height, padding
        self._lead_icon, self._muted, self._column_lines = lead_icon, muted, column_lines
        self._layout = vbox(self)
        self._header = None
        if header:
            self._header = QFrame()
            set_cls(self._header, "table-head")
            self._header.setFixedHeight(30)
            head_layout = hbox(self._header, (0, 0, 0, 0))
            if lead_icon:
                spacer = QWidget()
                spacer.setFixedWidth(36)
                head_layout.addWidget(spacer)
            for name, stretch in columns:
                head_layout.addWidget(set_cls(QLabel(name), "cell-head"), stretch)
            self._layout.addWidget(self._header)
        self._body = vbox()
        self._layout.addLayout(self._body)

    def set_rows(self, rows: list[tuple[str, ...]]) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, values in enumerate(rows):
            row = QFrame()
            first = index == 0 and self._header is None
            set_cls(row, "table-row-first" if first else ("table-row-muted" if self._muted else "table-row"))
            row.setFixedHeight(self._row_height)
            layout = hbox(row)
            if self._lead_icon:
                icon = QLabel()
                icon.setFixedWidth(36)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                manager().bind_icon(icon, self._lead_icon, "fg3", 13)
                layout.addWidget(icon)
            for col, (value, (_name, stretch)) in enumerate(zip(values, self._columns)):
                mono = self._mono[col] if col < len(self._mono) else False
                role = self._roles[col] if col < len(self._roles) else "fg"
                cell = ElidedLabel(value, role, px=self._px, mono=mono)
                cell.setToolTip(value if len(value) > 40 else "")
                container = QWidget()
                if col < len(self._columns) - 1 and self._column_lines:
                    set_cls(container, "cell")
                inner = hbox(container, (self._padding, 0, self._padding, 0))
                inner.addWidget(cell)
                layout.addWidget(container, stretch)
            self._body.addWidget(row)


def caps_label(text: str) -> QLabel:
    """Small uppercase section label (letter-spaced)."""
    widget = QLabel(text.upper())
    set_cls(widget, "caps")
    font = ui_font(11, 600)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.66)
    widget.setFont(font)
    return widget
