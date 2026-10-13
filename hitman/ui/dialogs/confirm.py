"""Small confirmation dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from hitman.ui.dialogs.base import OverlayDialog
from hitman.ui.widgets.common import button, label, vbox


class ConfirmDialog(OverlayDialog):
    """Ask a question. `choice` is the key of the clicked button, or None if dismissed."""

    def __init__(self, parent: QWidget, title: str, message: str, buttons: list[tuple[str, str, str]]):
        """`buttons` is a list of (key, text, style class), rendered left to right."""
        super().__init__(parent, 440, 200)
        self.choice: str | None = None
        self.add_header(title, bordered=False)
        body = vbox(margins=(20, 6, 20, 18))
        body.addWidget(label(message, "muted", wrap=True))
        body.addStretch(1)
        self.card_layout.addLayout(body, 1)
        widgets = []
        for key, text, cls in buttons:
            widgets.append(button(text, cls, height=34, on_click=lambda k=key: self._choose(k)))
        self.add_footer("", widgets)
        self.card.adjustSize()
        self._card_size = (440, max(180, self.card.sizeHint().height()))

    def _choose(self, key: str) -> None:
        self.choice = key
        self.accept()


def confirm(parent: QWidget, title: str, message: str, confirm_text: str, *, danger: bool = True) -> bool:
    dialog = ConfirmDialog(parent, title, message,
                           [("cancel", "Cancel", "secondary"), ("ok", confirm_text, "danger" if danger else "primary")])
    dialog.exec()
    return dialog.choice == "ok"


def alert(parent: QWidget, title: str, message: str) -> None:
    ConfirmDialog(parent, title, message, [("ok", "OK", "primary")]).exec()
