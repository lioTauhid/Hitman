"""Breadcrumb with the request name (double-click to rename) and the Code / Save buttons."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QSizePolicy, QWidget

from hitman.ui.fonts import ui_font
from hitman.ui.theme import manager, set_cls
from hitman.ui.widgets.common import ElidedLabel, IconButton, RoleLabel, button, hbox, label


class _NameLabel(ElidedLabel):
    """Request name: as wide as its text, shrinking with an ellipsis when space runs out."""

    double_clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(min(60, self.sizeHint().width()), self.sizeHint().height())

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()


class RequestHeader(QWidget):
    open_code = Signal()
    save = Signal()
    save_menu = Signal(QWidget)
    rename = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = hbox(self, (16, 12, 16, 0), 10)

        crumbs = hbox(spacing=6)
        self._icon = QLabel()
        manager().bind_icon(self._icon, "layers", "fg3", 14)
        crumbs.addWidget(self._icon)
        self._path = RoleLabel("", "fg3", px=12.5)
        crumbs.addWidget(self._path, 0)
        self._name = _NameLabel("", "fg", px=14, weight=600)
        self._name.setToolTip("Double-click to rename")
        self._name.double_clicked.connect(self._start_rename)
        crumbs.addWidget(self._name)
        self._editor = QLineEdit()
        set_cls(self._editor, "inline")
        self._editor.setFont(ui_font(14, 600))
        self._editor.setFixedHeight(28)
        self._editor.hide()
        self._editor.editingFinished.connect(self._finish_rename)
        crumbs.addWidget(self._editor)
        self._dirty = label("Unsaved changes", "pill")
        crumbs.addWidget(self._dirty)
        crumbs.addStretch(1)
        layout.addLayout(crumbs, 1)

        code = button("Code", "outline", icon="code", height=30, on_click=self.open_code.emit)
        code.setToolTip("Generate code")
        layout.addWidget(code)
        group = QFrame()
        group.setObjectName("SaveGroup")
        group.setFixedHeight(30)
        group_layout = hbox(group)
        save = button("Save", icon="save", icon_role="fg", height=28, on_click=self.save.emit)
        save.setObjectName("SaveButton")
        save.setToolTip("Save request")
        group_layout.addWidget(save)
        more = IconButton("chevD", "More save options", size=(26, 28), icon_size=13, stroke=2, radius=0)
        more.setObjectName("SaveMenuButton")
        more.clicked.connect(lambda: self.save_menu.emit(more))
        group_layout.addWidget(more)
        layout.addWidget(group)

    def set_state(self, name: str, breadcrumb: list[str], dirty: bool) -> None:
        self._name.setText(name)
        self._name.updateGeometry()
        path = " / ".join(breadcrumb) + " /" if breadcrumb else ""
        self._path.setText(self._path.fontMetrics().elidedText(path, Qt.TextElideMode.ElideMiddle, 360))
        self._path.setToolTip(path)
        self._path.setVisible(bool(breadcrumb))
        self._icon.setVisible(bool(breadcrumb))
        self._dirty.setVisible(dirty)

    def _start_rename(self) -> None:
        self._editor.setText(self._name.text())
        self._editor.setMinimumWidth(max(220, self._name.width() + 40))
        self._name.hide()
        self._editor.show()
        self._editor.setFocus()
        self._editor.selectAll()

    def _finish_rename(self) -> None:
        if not self._editor.isVisible():
            return
        text = self._editor.text().strip()
        self._editor.hide()
        self._name.show()
        if text and text != self._name.text():
            self.rename.emit(text)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._editor.isVisible():
            self._editor.setText(self._name.text())
            self._finish_rename()
            return
        super().keyPressEvent(event)
