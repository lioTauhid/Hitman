"""Value cell for form-data file fields: pick, show, replace or clear the file to upload."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QLabel, QSizePolicy, QWidget

from hitman.core.formatting import human_bytes
from hitman.ui.theme import manager
from hitman.ui.widgets.common import CardButton, ElidedLabel, IconButton, RoleLabel, button, hbox

_last_dir = str(Path.home())  # remembered across pickers during a session


class FileField(QWidget):
    changed = Signal()  # the user picked or cleared a file

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._path = ""
        self._dim = False
        self._enabled = True
        self.setAcceptDrops(True)
        layout = hbox(self, (8, 0, 6, 0), 6)

        self.pick = button("Select file…", "link", on_click=self._choose)
        self.pick.setToolTip("Choose a file to upload (or drop one here)")
        layout.addWidget(self.pick)

        self.chip = CardButton("file-chip")  # sized from its contents, unlike a plain QPushButton
        self.chip.setCheckable(False)
        self.chip.setFixedHeight(24)
        self.chip.clicked.connect(self._choose)
        chip_layout = hbox(self.chip, (7, 0, 3, 0), 6)
        self._icon = QLabel()
        manager().bind_icon(self._icon, "file", "fg3", 13)
        self._name = ElidedLabel("", "fg", px=12, mono=True, elide=Qt.TextElideMode.ElideMiddle)
        self._name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)  # hug the name
        for child in (self._icon, self._name):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            chip_layout.addWidget(child)
        self._clear = IconButton("x", "Remove file", size=(18, 18), icon_size=11, role="fg3", stroke=2, radius=4)
        self._clear.clicked.connect(self._remove)
        chip_layout.addWidget(self._clear)
        layout.addWidget(self.chip)

        self._note = RoleLabel("form-data only", "fg3", px=11.5)
        layout.addWidget(self._note)
        layout.addStretch(1)
        self._refresh()

    # -------------------------------------------------------------- state
    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        if path != self._path:
            self._path = path
            self._refresh()

    def set_dim(self, dim: bool) -> None:
        """Muted look for disabled rows."""
        self._dim = dim
        self._refresh()

    def set_files_enabled(self, enabled: bool) -> None:
        """Url-encoded bodies can't carry files: the file stays, but can't be changed and isn't sent."""
        self._enabled = enabled
        self._refresh()

    def _refresh(self) -> None:
        has = bool(self._path)
        self.pick.setVisible(not has)
        self.pick.setEnabled(self._enabled)
        self.chip.setVisible(has)
        self.chip.setEnabled(self._enabled)
        self._note.setVisible(not self._enabled)
        if not has:
            return
        file_path = Path(self._path).expanduser()
        exists = file_path.is_file()
        self._name.setText(file_path.name or self._path)
        self._name.set_role("fg3" if self._dim or not self._enabled else ("fg" if exists else "err"))
        if exists:
            self.chip.setToolTip(f"{self._path}\n{human_bytes(file_path.stat().st_size)} · click to change")
        else:
            self.chip.setToolTip(f"File not found: {self._path}\nClick to choose another file")
        self.chip.setAccessibleName(f"File {file_path.name}")

    # ------------------------------------------------------------ actions
    def _choose(self) -> None:
        global _last_dir
        start = str(Path(self._path).expanduser().parent) if self._path else _last_dir
        path, _ = QFileDialog.getOpenFileName(self, "Select a file to upload", start)
        if path:
            _last_dir = str(Path(path).parent)
            self.set_path(path)
            self.changed.emit()

    def _remove(self) -> None:
        self.set_path("")
        self.changed.emit()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._enabled and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files and Path(files[0]).is_file():
            self.set_path(files[0])
            self.changed.emit()
