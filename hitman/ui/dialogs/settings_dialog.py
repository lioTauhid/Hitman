"""Settings dialog. Every change is saved immediately."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QWidget)

from hitman import APP_NAME, AUTHOR, AUTHOR_URL, REPO_URL, __version__
from hitman.paths import data_dir, display_path
from hitman.services.workspace import Workspace
from hitman.ui.dialogs.base import OverlayDialog
from hitman.ui.fonts import mono_font
from hitman.ui.shortcuts import SHORTCUTS, display_keys
from hitman.ui.theme import set_cls
from hitman.ui.title_bar import app_logo
from hitman.ui.widgets.common import (IconButton, RoleLabel, SegmentedControl, ToggleSwitch, button, hbox, label,
                                      vbox)

SECTIONS = [("general", "General", "sliders"), ("requests", "Requests", "send"),
            ("shortcuts", "Shortcuts", "keyboard"), ("about", "About", "info")]


class SettingsDialog(OverlayDialog):
    def __init__(self, parent: QWidget, workspace: Workspace, section: str = "general"):
        super().__init__(parent, 760, 520)
        self.workspace = workspace
        content = hbox()

        nav = QFrame()
        set_cls(nav, "side-panel-full")
        nav.setFixedWidth(200)
        nav_layout = vbox(nav, (10, 16, 10, 16), 2)
        title = label("Settings", "h2")
        title.setContentsMargins(10, 0, 10, 10)
        nav_layout.addWidget(title)
        group = QButtonGroup(self)
        self._nav: dict[str, object] = {}
        for key, text, icon in SECTIONS:
            item = button(text, "nav", icon=icon, icon_size=15, height=34, on_click=lambda k=key: self.show_section(k))
            item.setCheckable(True)
            group.addButton(item)
            self._nav[key] = item
            nav_layout.addWidget(item)
        nav_layout.addStretch(1)
        content.addWidget(nav)

        right = vbox()
        head = hbox(margins=(24, 16, 16, 12), spacing=12)
        self.section_title = label("", "h3")
        head.addWidget(self.section_title, 1)
        close = IconButton("x", "Close settings", size=(30, 30), icon_size=15, stroke=2)
        close.clicked.connect(self.accept)
        head.addWidget(close)
        right.addLayout(head)
        self.pages = QStackedWidget()
        for builder in (self._general, self._requests, self._shortcuts, self._about):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            page = QWidget()
            layout = vbox(page, (24, 0, 24, 20), 0)
            builder(layout)
            layout.addStretch(1)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        right.addWidget(self.pages, 1)
        footer = QFrame()
        set_cls(footer, "dialog-footer")
        footer.setStyleSheet("QFrame { border-bottom-left-radius: 0; }")
        footer_layout = hbox(footer, (24, 12, 16, 12), 8)
        footer_layout.addWidget(label("Changes are saved as you make them.", "hint"), 1)
        footer_layout.addWidget(button("Done", "primary", height=34, on_click=self.accept))
        right.addWidget(footer)
        content.addLayout(right, 1)
        self.card_layout.addLayout(content, 1)
        self.show_section(section)

    def show_section(self, key: str) -> None:
        keys = [k for k, _, _ in SECTIONS]
        key = key if key in keys else "general"
        self._nav[key].setChecked(True)
        self.section_title.setText(dict((k, t) for k, t, _ in SECTIONS)[key])
        self.pages.setCurrentIndex(keys.index(key))

    # ------------------------------------------------------------ rows
    @staticmethod
    def _row(title: str, description: str, control: QWidget) -> QFrame:
        row = QFrame()
        set_cls(row, "setting-row")
        layout = hbox(row, (0, 12, 0, 12), 16)
        text = vbox(spacing=2)
        text.addWidget(RoleLabel(title, "fg", px=12.5, weight=500))
        text.addWidget(label(description, "hint", wrap=True))
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _toggle(self, key: str, title: str, description: str) -> QFrame:
        switch = ToggleSwitch(getattr(self.workspace.settings, key))
        switch.setAccessibleName(title)
        switch.toggled.connect(lambda on: self.workspace.update_settings(**{key: on}))
        return self._row(title, description, switch)

    def _number(self, key: str, title: str, description: str, maximum: int) -> QFrame:
        edit = QLineEdit(str(getattr(self.workspace.settings, key)))
        edit.setValidator(QIntValidator(0, maximum, edit))
        edit.setFixedSize(120, 32)
        edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        edit.setProperty("mono", "true")
        edit.setFont(mono_font(12.5))
        edit.setAccessibleName(title)
        edit.textEdited.connect(lambda text: self._save_number(key, text))
        return self._row(title, description, edit)

    def _save_number(self, key: str, text: str) -> None:
        if text.isdigit():
            self.workspace.update_settings(**{key: int(text)})

    # ----------------------------------------------------------- pages
    def _general(self, layout) -> None:
        s = self.workspace.settings
        theme_seg = SegmentedControl([("dark", "Dark"), ("light", "Light"), ("system", "System")], s.theme, large=True)
        theme_seg.changed.connect(lambda v: self.workspace.update_settings(theme=v))
        layout.addWidget(self._row("Theme", "Dark is easier on the eyes for long sessions.", theme_seg))
        sizes = [(str(n), f"{n} px") for n in (12, 13, 14, 15)]
        size_seg = SegmentedControl(sizes, str(s.font_size), large=True)
        size_seg.changed.connect(lambda v: self.workspace.update_settings(font_size=int(v)))
        layout.addWidget(self._row("Editor font size", "Used in the URL bar, body editor and response viewer.", size_seg))
        layout.addWidget(self._toggle("open_in_new_tab", "Open requests in a new tab",
                                      "Otherwise the current tab is replaced if it has no changes."))
        layout.addWidget(self._toggle("ask_before_close", "Ask before closing unsaved tabs",
                                      "Prevents losing edits you have not saved."))
        layout.addWidget(self._toggle("restore_tabs", "Restore open tabs on launch",
                                      "Pick up exactly where you left off."))

    def _requests(self, layout) -> None:
        layout.addWidget(self._number("timeout_ms", "Request timeout", "Milliseconds. 0 means wait forever.", 3_600_000))
        layout.addWidget(self._number("max_redirects", "Maximum redirects", "Stop following after this many hops.", 100))
        layout.addWidget(self._toggle("follow_redirects", "Follow redirects", "Follow 3xx responses automatically."))
        layout.addWidget(self._toggle("verify_ssl", "Verify SSL certificates",
                                      "Turn off only for local servers with self-signed certificates."))
        layout.addWidget(self._toggle("encode_url", "Encode URLs automatically",
                                      "Percent-encode special characters before sending."))
        layout.addWidget(self._toggle("use_system_proxy", "Use system proxy",
                                      "Send requests through the proxy set in your operating system."))

    def _shortcuts(self, layout) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(0)
        for i, (_action, text, sequence) in enumerate(SHORTCUTS):
            row = QFrame()
            set_cls(row, "setting-row")
            row.setMinimumHeight(40)
            row_layout = hbox(row, spacing=10)
            row_layout.addWidget(label(text, "body"), 1)
            for key in display_keys(sequence):
                cap = set_cls(QLabel(key), "kbd-lg")
                cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(cap)
            grid.addWidget(row, i // 2, i % 2)
        layout.addLayout(grid)

    def _about(self, layout) -> None:
        layout.addSpacing(8)
        head = hbox(spacing=14)
        head.addWidget(app_logo(52, 14, 30))
        names = vbox(spacing=2)
        names.addWidget(RoleLabel(APP_NAME, "fg", px=18, weight=600))
        names.addWidget(label(f"Desktop API client · version {__version__}", "muted"))
        head.addLayout(names, 1)
        layout.addLayout(head)
        layout.addSpacing(14)
        info = QGridLayout()
        info.setHorizontalSpacing(18)
        info.setVerticalSpacing(6)
        creator = QWidget()
        creator_row = hbox(creator, spacing=6)
        creator_row.addWidget(RoleLabel(AUTHOR, "fg", px=12.5))
        creator_row.addWidget(label("·", "muted"))
        creator_row.addWidget(_link("LinkedIn", AUTHOR_URL))
        rows = [("Data folder", RoleLabel(display_path(data_dir()), "fg", px=12.5, mono=True)),
                ("Storage", RoleLabel("SQLite database, kept in the data folder", "fg", px=12.5)),
                ("Sync", RoleLabel("Local only. No account needed.", "fg", px=12.5)),
                ("Source code", _link(REPO_URL.removeprefix("https://"), REPO_URL)),
                ("Created by", creator)]
        for i, (key, value) in enumerate(rows):
            info.addWidget(label(key, "muted"), i, 0)
            info.addWidget(value, i, 1, Qt.AlignmentFlag.AlignLeft)
        info.setColumnStretch(1, 1)
        layout.addLayout(info)
        layout.addSpacing(14)
        actions = hbox(spacing=8)
        actions.addWidget(button("Open data folder", height=32,
                                 on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))))
        actions.addStretch(1)
        layout.addLayout(actions)


def _link(text: str, url: str) -> QPushButton:
    """A text link that opens `url` in the browser."""
    link = button(text, "link", on_click=lambda: QDesktopServices.openUrl(QUrl(url)))
    link.setToolTip(url)
    return link
