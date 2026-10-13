"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from hitman import APP_NAME, __version__
from hitman.paths import database_path
from hitman.services.workspace import Workspace
from hitman.storage.database import Database
from hitman.ui import icons
from hitman.ui.fonts import load_fonts, ui_font
from hitman.ui.main_window import MainWindow
from hitman.ui.theme import ACCENT, ON_ACCENT, ThemeManager


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        inset = size * 0.08
        painter.drawRoundedRect(QRectF(inset, inset, size - 2 * inset, size - 2 * inset), size * 0.22, size * 0.22)
        glyph = size * 0.56
        icons.paint(painter, "bolt", ON_ACCENT, QRectF((size - glyph) / 2, (size - glyph) / 2, glyph, glyph))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def main() -> None:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationName(APP_NAME)
    app = QApplication(sys.argv)
    load_fonts()
    app.setFont(ui_font(13))
    app.setWindowIcon(app_icon())

    workspace = Workspace(Database(database_path()))
    ThemeManager(app).configure(workspace.settings.theme, workspace.settings.font_size)
    window = MainWindow(workspace)
    window.show()
    code = app.exec()
    workspace.db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
