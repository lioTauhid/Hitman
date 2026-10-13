"""Export collection dialog with a live JSON preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QWidget)

from hitman.core.exporters import FORMATS, export, to_json
from hitman.core.formatting import human_bytes, slug
from hitman.core.models import Collection, Variable, count_requests
from hitman.paths import display_path
from hitman.ui.dialogs.base import OverlayDialog
from hitman.ui.dialogs.confirm import alert, confirm
from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls, theme
from hitman.ui.widgets.code_editor import CodeEditor
from hitman.ui.widgets.common import CardButton, CheckRow, ElidedLabel, RoleLabel, button, hbox, label, vbox

PREVIEW_LINE_LIMIT = 2000


class RadioMark(QWidget):
    """The small ring-with-dot indicator used inside option cards."""

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._button = button
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        button.toggled.connect(self.update)
        manager().changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self._button.isChecked()
        pen = painter.pen()
        pen.setColor(t.c("accent_text") if on else t.c("line_strong"))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(0.75, 0.75, 12.5, 12.5))
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.c("accent_text"))
            painter.drawEllipse(QRectF(4, 4, 6, 6))


def option_card(title: str, subtitle: str = "", meta: str = "", badge: str = "") -> CardButton:
    card = CardButton("option", title)
    card.setStyleSheet("border-radius: 8px;")
    row = hbox(card, (11, 8, 11, 8), 10)
    row.addWidget(RadioMark(card))
    text = vbox(spacing=1)
    text.addWidget(RoleLabel(title, "fg", px=12.5, weight=500))
    if subtitle:
        text.addWidget(RoleLabel(subtitle, "fg3", px=11.5))
    row.addLayout(text, 1)
    if meta:
        row.addWidget(RoleLabel(meta, "fg3", px=11.5))
    if badge:
        row.addWidget(set_cls(QLabel(badge), "badge"))
    card.setMinimumHeight(38)
    return card.finish()


class ExportDialog(OverlayDialog):
    """Writes the file itself; `exported_path` is set on success."""

    def __init__(self, parent: QWidget, collections: list[Collection], selected_id: str | None,
                 env_variables: list[Variable]):
        super().__init__(parent, 900, 600)
        self.exported_path: Path | None = None
        self._collections = collections
        self._env_vars = env_variables
        self._folder = Path.home() / "Downloads" if (Path.home() / "Downloads").is_dir() else Path.home()
        self._file_name_edited = False
        self._json = ""
        self._sel = selected_id if any(c.id == selected_id for c in collections) else collections[0].id
        self._fmt = "hitman"

        self.add_header("Export collection",
                        "Save a collection as a JSON file to back it up, version it in git, or share it with your team.",
                        icon="export")
        content = hbox()
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setFixedWidth(400)
        set_cls(form_scroll, "form-pane")
        form = QWidget()
        layout = vbox(form, (20, 18, 20, 18), 18)

        layout.addLayout(self._group("Collection", [
            (c.id, option_card(c.name, meta=f"{count_requests(c.items)} requests")) for c in collections],
            self._sel, self._pick_collection))
        layout.addLayout(self._group("Format", [
            (key, option_card(title, desc, badge="Native" if key == "hitman" else ""))
            for key, title, desc, _suffix in FORMATS], self._fmt, self._pick_format))

        include = vbox(spacing=9)
        include.addWidget(label("Include", "section"))
        self.include_env = self._check("Environment variables",
                                       "From the active environment; secret values are left out", True)
        self.pretty = self._check("Pretty-print JSON", "Two-space indent; turn off for a smaller file", True)
        include.addWidget(self.include_env)
        include.addWidget(self.pretty)
        layout.addLayout(include)

        file_box = vbox(spacing=6)
        file_box.addWidget(label("File name", "section"))
        self.file_name = QLineEdit()
        self.file_name.setProperty("mono", "true")
        self.file_name.setFont(mono_font(12))
        self.file_name.setFixedHeight(34)
        self.file_name.textEdited.connect(self._on_file_edit)
        file_box.addWidget(self.file_name)
        folder_row = hbox(spacing=8)
        icon = QLabel()
        manager().bind_icon(icon, "folder", "fg3", 14)
        folder_row.addWidget(icon)
        self.folder_label = ElidedLabel(display_path(self._folder), "fg2", px=12, mono=True,
                                        elide=Qt.TextElideMode.ElideMiddle)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(button("Change…", "link", on_click=self._change_folder))
        file_box.addLayout(folder_row)
        layout.addLayout(file_box)
        layout.addStretch(1)
        form_scroll.setWidget(form)
        content.addWidget(form_scroll)

        preview = QFrame()
        set_cls(preview, "preview")
        preview_layout = vbox(preview)
        bar = QFrame()
        bar.setFixedHeight(44)
        set_cls(bar, "bar")
        bar_layout = hbox(bar, (16, 0, 12, 0), 10)
        bar_layout.addWidget(label("Preview", "section"))
        self.stats = RoleLabel("", "fg3", px=11.5, mono=True)
        bar_layout.addWidget(self.stats, 1)
        self.copy_button = button("Copy JSON", icon="copy", icon_role="fg", icon_size=13, height=28,
                                  on_click=self._copy)
        bar_layout.addWidget(self.copy_button)
        preview_layout.addWidget(bar)
        self.preview = CodeEditor(read_only=True, framed=False, gutter_border=False, font_px=12)
        self.preview.set_language("JSON")
        preview_layout.addWidget(self.preview, 1)
        content.addWidget(preview, 1)
        self.card_layout.addLayout(content, 1)

        hint = QWidget()
        hint_row = hbox(hint, spacing=7)
        lock = QLabel()
        manager().bind_icon(lock, "lock", "fg3", 14)
        hint_row.addWidget(lock)
        hint_row.addWidget(label("Secret values are never exported.", "hint"), 1)
        export_button = button("Export JSON", "primary", icon="import", icon_role="on_accent", icon_size=14,
                               height=34, on_click=self._export)
        self.add_footer(hint, [self.cancel_button(self), export_button])
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self._set_copied(False))
        self._refresh()

    # ------------------------------------------------------------ builders
    def _group(self, title: str, cards: list[tuple[str, QPushButton]], current: str, on_pick) -> object:
        box = vbox(spacing=8)
        box.addWidget(label(title, "section"))
        group = QButtonGroup(self)
        cards_box = vbox(spacing=4)
        for key, card in cards:
            group.addButton(card)
            card.setChecked(key == current)
            card.clicked.connect(lambda _c=False, k=key: on_pick(k))
            cards_box.addWidget(card)
        box.addLayout(cards_box)
        return box

    def _check(self, title: str, desc: str, checked: bool) -> CheckRow:
        row = CheckRow(title, desc, checked)
        row.toggled.connect(lambda _on: self._refresh())
        return row

    # -------------------------------------------------------------- state
    def _collection(self) -> Collection:
        return next(c for c in self._collections if c.id == self._sel)

    def _pick_collection(self, key: str) -> None:
        self._sel = key
        self._refresh()

    def _pick_format(self, key: str) -> None:
        self._fmt = key
        self._refresh()

    def _on_file_edit(self, _text: str) -> None:
        self._file_name_edited = True

    def _refresh(self) -> None:
        collection = self._collection()
        suffix = next(f[3] for f in FORMATS if f[0] == self._fmt)
        if not self._file_name_edited:
            self.file_name.setText(slug(collection.name) + suffix)
        extra = self._env_vars if self.include_env.isChecked() else None
        self._json = to_json(export(collection, self._fmt, extra), pretty=self.pretty.isChecked())
        lines = self._json.count("\n") + 1
        shown = self._json if lines <= PREVIEW_LINE_LIMIT else "\n".join(self._json.splitlines()[:PREVIEW_LINE_LIMIT])
        self.preview.set_text(shown)
        self.stats.setText(f"{lines} lines · {human_bytes(len(self._json.encode()))}")

    def _change_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", str(self._folder))
        if folder:
            self._folder = Path(folder)
            self.folder_label.setText(display_path(self._folder))

    def _set_copied(self, copied: bool) -> None:
        self.copy_button.setText("Copied" if copied else "Copy JSON")
        manager().bind_icon(self.copy_button, "check" if copied else "copy", "fg", 13)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._json)
        self._set_copied(True)
        self._copy_timer.start(1600)

    def _export(self) -> None:
        name = self.file_name.text().strip() or "collection.json"
        path = self._folder / name
        if path.exists() and not confirm(self, "Replace file?", f"{display_path(path)} already exists.", "Replace"):
            return
        try:
            path.write_text(self._json, encoding="utf-8")
        except OSError as exc:
            alert(self, "Export failed", f"Could not write {display_path(path)}: {exc.strerror or exc}")
            return
        self.exported_path = path
        self.accept()
