"""Import dialog: pick a file or paste collection JSON / OpenAPI / a cURL command."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QPlainTextEdit, QStackedWidget, QWidget

from hitman.core.formatting import human_bytes
from hitman.core.importers import SUPPORTED_FORMATS, ImportFormatError, ImportResult, parse_import
from hitman.ui.dialogs.base import OverlayDialog
from hitman.ui.fonts import mono_font
from hitman.ui.theme import manager, set_cls
from hitman.ui.widgets.common import ColorDot, ElidedLabel, IconButton, RoleLabel, button, hbox, label, vbox
from hitman.ui.widgets.popover import chip_label
from hitman.ui.widgets.tabs import UnderlineTabs

MAX_FILE_BYTES = 25 * 1024 * 1024


class ImportDialog(OverlayDialog):
    """On accept, `result` holds the parsed ImportResult."""

    def __init__(self, parent: QWidget):
        super().__init__(parent, 640, 480)
        self.result: ImportResult | None = None
        self._file: tuple[str, int, str] | None = None  # (name, size, text)
        self._error: str | None = None
        self.setAcceptDrops(True)

        self.add_header("Import", "Bring in a collection file or paste a cURL command.", bordered=False)
        tabs_frame = QFrame()
        tabs_frame.setObjectName("SectionTabs")
        tabs_layout = vbox(tabs_frame, (16, 12, 16, 0))
        self.tabs = UnderlineTabs([("file", "File", "file"), ("raw", "Paste text", "code")], margins=(0, 0, 0, 0))
        self.tabs.changed.connect(lambda _k: self._refresh())
        tabs_layout.addWidget(self.tabs)
        self.card_layout.addWidget(tabs_frame)

        body = vbox(margins=(20, 18, 20, 18), spacing=16)
        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self._build_drop())
        self.source_stack.addWidget(self._build_paste())
        body.addWidget(self.source_stack, 1)
        body.addWidget(self._build_source_card())
        self.summary = QFrame()
        set_cls(self.summary, "note")
        summary_row = hbox(self.summary, (12, 10, 12, 10), 10)
        icon = QLabel()
        manager().bind_icon(icon, "layers", "accent_text", 15)
        summary_row.addWidget(icon)
        self.summary_text = label("", "body", wrap=True)
        summary_row.addWidget(self.summary_text, 1)
        body.addWidget(self.summary)
        self.card_layout.addLayout(body, 1)

        self.import_button = button("Import", "primary", height=34, on_click=self._do_import)
        self.add_footer("Imported data stays on this machine.", [self.cancel_button(self), self.import_button])
        self._refresh()

    # -------------------------------------------------------------- build
    def _build_drop(self) -> QWidget:
        page = QWidget()
        layout = vbox(page, spacing=16)
        self.drop = QFrame()
        set_cls(self.drop, "drop-zone")
        self.drop.setMinimumHeight(190)
        drop_layout = vbox(self.drop, (20, 20, 20, 20), 10)
        drop_layout.addStretch(1)
        tile = QLabel()
        tile.setFixedSize(44, 44)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setStyleSheet("border-radius: 12px;")
        set_cls(tile, "icon-tile")
        manager().bind_icon(tile, "upload", "accent_text", 22)
        drop_layout.addWidget(tile, 0, Qt.AlignmentFlag.AlignHCenter)
        drop_layout.addWidget(RoleLabel("Drop a file here", "fg", px=13.5, weight=600), 0, Qt.AlignmentFlag.AlignHCenter)
        drop_layout.addWidget(label("Each file becomes its own collection.", "muted"), 0, Qt.AlignmentFlag.AlignHCenter)
        choose = button("Choose file…", "secondary", height=32, on_click=self._choose)
        drop_layout.addWidget(choose, 0, Qt.AlignmentFlag.AlignHCenter)
        drop_layout.addStretch(1)
        layout.addWidget(self.drop)
        chips = hbox(spacing=8)
        chips.addWidget(label("Supported", "section"))
        for fmt in SUPPORTED_FORMATS:
            chips.addWidget(chip_label(fmt))
        chips.addStretch(1)
        layout.addLayout(chips)
        layout.addStretch(1)
        return page

    def _build_paste(self) -> QWidget:
        page = QWidget()
        layout = vbox(page, spacing=8)
        layout.addWidget(label("Paste collection JSON, an OpenAPI spec or a cURL command", "section"))
        self.paste = QPlainTextEdit()
        set_cls(self.paste, "dialog")
        self.paste.setFont(mono_font(12))
        self.paste.setPlaceholderText("curl -X POST https://api.example.com/v1/orders -H 'Content-Type: application/json' -d '{…}'")
        self.paste.setMinimumHeight(150)
        self.paste.textChanged.connect(self._refresh)
        layout.addWidget(self.paste, 1)
        return page

    def _build_source_card(self) -> QFrame:
        self.card_frame = QFrame()
        set_cls(self.card_frame, "card")
        row = hbox(self.card_frame, (14, 12, 14, 12), 12)
        tile = QLabel()
        set_cls(tile, "icon-tile")
        tile.setFixedSize(38, 38)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        manager().bind_icon(tile, "file", "fg2", 18)
        row.addWidget(tile)
        text = vbox(spacing=3)
        self.src_name = ElidedLabel("", "fg", px=12.5, mono=True)
        text.addWidget(self.src_name)
        meta = hbox(spacing=8)
        self.src_size = label("", "hint")
        meta.addWidget(self.src_size)
        meta.addWidget(label("·", "hint"))
        self.src_dot = ColorDot("ok", 6)
        meta.addWidget(self.src_dot)
        self.src_kind = RoleLabel("", "ok", px=12)
        meta.addWidget(self.src_kind, 1)
        text.addLayout(meta)
        row.addLayout(text, 1)
        remove = IconButton("x", "Remove", icon_size=14, role="fg3", stroke=2)
        remove.clicked.connect(self._clear)
        row.addWidget(remove)
        return self.card_frame

    # ------------------------------------------------------------- source
    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a collection file", str(Path.home()),
                                              "Collections (*.json *.yaml *.yml *.txt *.sh);;All files (*)")
        if path:
            self._load_file(Path(path))

    def _load_file(self, path: Path) -> None:
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                self._file, self._error = (path.name, size, ""), "File is too large to import."
            else:
                self._file, self._error = (path.name, size, path.read_text(encoding="utf-8", errors="replace")), None
        except OSError as exc:
            self._file, self._error = (path.name, 0, ""), f"Could not read the file: {exc.strerror or exc}"
        self.tabs.set_current("file")
        self._refresh()

    def _clear(self) -> None:
        if self.tabs.current() == "file":
            self._file = None
        else:
            self.paste.clear()
        self._refresh()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            set_cls(self.drop, "drop-zone-active")

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        set_cls(self.drop, "drop-zone")

    def dropEvent(self, event) -> None:  # noqa: N802
        set_cls(self.drop, "drop-zone")
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self._load_file(Path(urls[0].toLocalFile()))

    # ------------------------------------------------------------ refresh
    def _refresh(self) -> None:
        tab = self.tabs.current()
        self.source_stack.setCurrentIndex(0 if tab == "file" else 1)
        self.result = None
        name = size = ""
        detail, ok = "", False
        if tab == "file" and self._file:
            name, size = self._file[0], human_bytes(self._file[1])
            if self._error:
                detail = self._error
            else:
                detail, ok = self._detect(self._file[2])
        elif tab == "raw" and self.paste.toPlainText().strip():
            text = self.paste.toPlainText()
            name, size = "Pasted text", f"{len(text)} chars"
            detail, ok = self._detect(text)
        has_source = bool(name)
        self.source_stack.setVisible(tab == "raw" or not self._file)
        self.card_frame.setVisible(has_source)
        if has_source:
            self.src_name.setText(name)
            self.src_size.setText(size)
            self.src_kind.setText(detail)
            self.src_kind.set_role("ok" if ok else "warn")
            self.src_dot.set_token("ok" if ok else "warn")
        self.summary.setVisible(ok)
        if ok and self.result:
            r = self.result
            if r.kind == "curl":
                self.summary_text.setText(f"Opens “{r.request.method} {r.title}” in a new tab")
            else:
                folders = f" · {r.folder_count} folders" if r.folder_count else ""
                count = r.request_count
                self.summary_text.setText(f"Creates the collection “{r.title}”{folders} · {count} request{'s' if count != 1 else ''}")
        self.import_button.setEnabled(ok)

    def _detect(self, text: str) -> tuple[str, bool]:
        try:
            self.result = parse_import(text)
        except ImportFormatError as exc:
            self.result = None
            return str(exc)[:90], False
        return self.result.label, True

    def _do_import(self) -> None:
        if self.result:
            self.accept()
