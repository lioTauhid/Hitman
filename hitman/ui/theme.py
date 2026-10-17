"""Design tokens, the application style sheet and live theme switching."""

from __future__ import annotations

import weakref
from string import Template

import shiboken6

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

from hitman.ui import icons
from hitman.ui.fonts import css_families, px_to_pt

ACCENT = "#C6F35B"
ON_ACCENT = "#121405"

DARK = {
    "bg": "#0E0F11", "surface": "#141518", "surface2": "#1A1C20", "surface3": "#24262B",
    "line": "#26292E", "line_strong": "#363A41",
    "fg": "#E9EAEC", "fg2": "#B0B4BA", "fg3": "#8A8F97",
    "get": "#5BD6A2", "post": "#F2C14E", "put": "#7DB0FF", "patch": "#B9A2FF",
    "delete": "#FF8080", "head": "#A0A6AE", "options": "#F293CB",
    "ok": "#5BD6A2", "warn": "#F2C14E", "err": "#FF8080",
    "syn_key": "#8EC5FF", "syn_str": "#BFE47F", "syn_num": "#F6AE84", "syn_bool": "#D3AAFF",
    "syn_null": "#A0A6AE", "syn_punc": "#80858D", "syn_kw": "#FF9FC8", "syn_fn": "#8EC5FF", "syn_com": "#7E848C",
    "ring_strong": "#7DB0FF", "scrim": "#A3050608", "selection": "#4D7DB0FF", "shadow": "#8C000000",
}

LIGHT = {
    "bg": "#EBECE8", "surface": "#F6F6F3", "surface2": "#FFFFFF", "surface3": "#ECEDE9",
    "line": "#DADBD5", "line_strong": "#C6C8C0",
    "fg": "#16171A", "fg2": "#474B51", "fg3": "#666A71",
    "get": "#0B7F57", "post": "#9A6500", "put": "#1D5FCF", "patch": "#6B43CC",
    "delete": "#C8323A", "head": "#5B6169", "options": "#AE3F78",
    "ok": "#0B7F57", "warn": "#9A6500", "err": "#C8323A",
    "syn_key": "#1D5BB8", "syn_str": "#3D7300", "syn_num": "#AE4F17", "syn_bool": "#6B43CC",
    "syn_null": "#666A71", "syn_punc": "#666A71", "syn_kw": "#B2306A", "syn_fn": "#1D5BB8", "syn_com": "#757A81",
    "ring_strong": "#1D5FCF", "scrim": "#6116171A", "selection": "#381D5FCF", "shadow": "#3316171A",
}


def _shade(color: QColor, amount: float) -> QColor:
    return QColor(round(color.red() * (1 - amount)), round(color.green() * (1 - amount)),
                  round(color.blue() * (1 - amount)))


def _alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(alpha)
    return c


def qss_color(color: QColor) -> str:
    if color.alpha() == 255:
        return color.name(QColor.NameFormat.HexRgb)
    return color.name(QColor.NameFormat.HexArgb)


class Theme:
    def __init__(self, name: str):
        self.name = name
        self.dark = name == "dark"
        self.colors = {k: QColor(v) for k, v in (DARK if self.dark else LIGHT).items()}
        accent = QColor(ACCENT)
        self.colors["accent"] = accent
        self.colors["accent_text"] = accent if self.dark else _shade(accent, 0.52)
        self.colors["accent_soft"] = _alpha(accent, 0.11 if self.dark else 0.30)
        self.colors["accent_soft2"] = _alpha(accent, 0.09 if self.dark else 0.22)
        self.colors["accent_hover"] = accent.lighter(107)
        self.colors["on_accent"] = QColor(ON_ACCENT)
        self.colors["on_check"] = QColor(ON_ACCENT if self.dark else "#FFFFFF")

    def c(self, name: str) -> QColor:
        return QColor(self.colors[name])

    def method(self, method: str) -> QColor:
        return self.c(method.lower()) if method.lower() in self.colors else self.c("fg")

    def status(self, code: int | None) -> QColor:
        if not code:
            return self.c("err")
        if code < 300:
            return self.c("ok")
        if code < 400:
            return self.c("put")
        if code < 500:
            return self.c("warn")
        return self.c("err")

    def env_color(self, token: str) -> QColor:
        return self.c(token) if token in self.colors else self.c("fg3")


class ThemeManager(QObject):
    """Owns the active Theme; re-styles the app and notifies widgets when it changes."""

    changed = Signal()
    _instance: ThemeManager | None = None

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.mode = "dark"
        self.editor_font_size = 13
        self.theme = Theme("dark")
        self._icon_bindings: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        app.styleHints().colorSchemeChanged.connect(lambda _scheme: self._refresh_if_system())
        ThemeManager._instance = self

    @classmethod
    def instance(cls) -> ThemeManager:
        assert cls._instance is not None, "ThemeManager not created"
        return cls._instance

    def configure(self, mode: str, editor_font_size: int | None = None) -> None:
        self.mode = mode
        if editor_font_size:
            self.editor_font_size = editor_font_size
        self._apply()

    def _resolved_name(self) -> str:
        if self.mode == "system":
            scheme = QGuiApplication.styleHints().colorScheme()
            return "light" if scheme == Qt.ColorScheme.Light else "dark"
        return "light" if self.mode == "light" else "dark"

    def _refresh_if_system(self) -> None:
        if self.mode == "system":
            self._apply()

    def _apply(self) -> None:
        self.theme = Theme(self._resolved_name())
        self.app.setPalette(build_palette(self.theme))
        self.app.setStyleSheet(build_style_sheet(self.theme))
        for widget, spec in list(self._icon_bindings.items()):
            if shiboken6.isValid(widget):
                self._set_icon(widget, *spec)
            else:
                del self._icon_bindings[widget]
        self.changed.emit()

    def bind_icon(self, widget: QWidget, name: str, role: str = "fg2", size: int = 16, stroke: float = 1.8) -> None:
        """Give a button or label an icon that follows the theme."""
        self._icon_bindings[widget] = (name, role, size, stroke)
        self._set_icon(widget, name, role, size, stroke)

    def _set_icon(self, widget: QWidget, name: str, role: str, size: int, stroke: float) -> None:
        color = self.theme.c(role)
        if isinstance(widget, QAbstractButton):
            widget.setIcon(icons.icon(name, color, size, stroke))
            widget.setIconSize(QSize(size, size))
        elif isinstance(widget, QLabel):
            widget.setPixmap(icons.pixmap(name, color, size, stroke))


def theme() -> Theme:
    return ThemeManager.instance().theme


def manager() -> ThemeManager:
    return ThemeManager.instance()


def build_palette(t: Theme) -> QPalette:
    p = QPalette()
    role = QPalette.ColorRole
    p.setColor(role.Window, t.c("bg"))
    p.setColor(role.WindowText, t.c("fg"))
    p.setColor(role.Base, t.c("surface2"))
    p.setColor(role.AlternateBase, t.c("surface"))
    p.setColor(role.Text, t.c("fg"))
    p.setColor(role.PlaceholderText, t.c("fg3"))
    p.setColor(role.Button, t.c("surface2"))
    p.setColor(role.ButtonText, t.c("fg"))
    p.setColor(role.Highlight, t.c("selection"))
    p.setColor(role.HighlightedText, t.c("fg"))
    p.setColor(role.ToolTipBase, t.c("surface2"))
    p.setColor(role.ToolTipText, t.c("fg"))
    p.setColor(role.Link, t.c("accent_text"))
    return p


_SIZES = (10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 15, 16, 18)

STYLE_SHEET = Template("""
* { outline: 0; }
QWidget { color: $fg; }
QMainWindow, #Root { background: $bg; }
#Root[framed="true"] { border: 1px solid $line_strong; }
QToolTip { background: $surface2; color: $fg; border: 1px solid $line_strong; border-radius: 6px; padding: 4px 8px; font-size: $fs12; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
QAbstractScrollArea { background: transparent; }

/* ---------- structure ---------- */
#TitleBar { background: $bg; border-bottom: 1px solid $line; }
#AppName { font-size: $fs13; }
#Rail { background: $bg; border-right: 1px solid $line; }
#Sidebar { background: $surface; border-right: 1px solid $line; }
#MainColumn, #RequestPane, #ResponsePane { background: $surface; }
#TabStrip { background: $bg; border-bottom: 1px solid $line; }
#SectionTabs, #ResponseHeader { border-bottom: 1px solid $line; }
#StatusBar { background: $bg; border-top: 1px solid $line; }
#StatusBar QLabel, #StatusBar QPushButton { color: $fg3; font-size: $fs11_5; }

/* ---------- labels ---------- */
QLabel { background: transparent; }
QLabel[cls="h2"] { font-size: $fs15; font-weight: 600; }
QLabel[cls="h3"] { font-size: $fs14; font-weight: 600; }
QLabel[cls="panel-title"] { font-size: $fs13; font-weight: 600; }
QLabel[cls="section"] { font-size: $fs12; font-weight: 600; color: $fg2; }
QLabel[cls="body"] { font-size: $fs12_5; }
QLabel[cls="strong"] { font-size: $fs12_5; font-weight: 500; }
QLabel[cls="muted"] { font-size: $fs12_5; color: $fg3; }
QLabel[cls="hint"] { font-size: $fs12; color: $fg3; }
QLabel[cls="small"] { font-size: $fs11_5; color: $fg3; }
QLabel[cls="tiny"] { font-size: $fs11; color: $fg3; }
QLabel[cls="caps"] { font-size: $fs11; font-weight: 600; color: $fg3; }
QLabel[cls="mono"] { font-family: $mono_family; font-size: $fs12; }
QLabel[cls="pill"] { font-size: $fs11; color: $fg2; border: 1px solid $line; border-radius: 9px; padding: 1px 8px; }
QLabel[cls="chip"] { font-size: $fs12; color: $fg2; border: 1px solid $line; border-radius: 13px; background: $surface2; padding: 4px 10px; }
QLabel[cls="badge"] { font-size: $fs10_5; font-weight: 600; color: $on_accent; background: $accent; border-radius: 8px; padding: 2px 7px; }
QLabel[cls="format"] { font-size: $fs11_5; font-weight: 600; color: $accent_text; border: 1px solid $line; border-radius: 6px; padding: 0 8px; }
QLabel[cls="kbd"] { font-family: $mono_family; font-size: $fs10_5; color: $fg2; padding: 2px 6px; border: 1px solid $line; border-radius: 4px; background: $surface2; }
QLabel[cls="kbd-lg"] { font-family: $mono_family; font-size: $fs11; color: $fg2; padding: 1px 6px; border: 1px solid $line_strong; border-bottom-width: 2px; border-radius: 5px; background: $surface2; min-width: 10px; }
QLabel[cls="icon-tile"] { background: $surface3; border-radius: 9px; }
QLabel[cls="error"] { font-size: $fs12; color: $err; }

/* ---------- buttons ---------- */
QPushButton { border: 1px solid $line; border-radius: 7px; background: $surface2; color: $fg; font-size: $fs12_5; font-weight: 500; padding: 0 11px; }
QPushButton:hover { background: $surface3; }
QPushButton:disabled { color: $fg3; }
QPushButton[cls="outline"] { background: transparent; color: $fg2; }
QPushButton[cls="outline"]:hover { background: $surface3; }
QPushButton[cls="ghost"] { background: transparent; border: 0; color: $fg2; }
QPushButton[cls="ghost"]:hover { background: $surface3; }
QPushButton[cls="primary"] { background: $accent; color: $on_accent; border: 0; border-radius: 8px; font-size: $fs13; font-weight: 600; padding: 0 16px; }
QPushButton[cls="primary"]:hover { background: $accent_hover; }
QPushButton[cls="primary"]:disabled { background: $accent_disabled; color: $on_accent_disabled; }
QPushButton[cls="secondary"] { border: 1px solid $line_strong; border-radius: 8px; background: $surface2; font-size: $fs13; padding: 0 14px; }
QPushButton[cls="secondary"]:hover { background: $surface3; }
QPushButton[cls="danger"] { background: $err; color: #FFFFFF; border: 0; border-radius: 8px; font-size: $fs13; font-weight: 600; padding: 0 16px; }
QPushButton[cls="link"] { border: 0; background: transparent; color: $accent_text; padding: 0; font-size: $fs12; font-weight: 500; }
QPushButton[cls="link"]:hover { color: $fg; }
QPushButton[cls="link-muted"] { border: 0; background: transparent; color: $fg3; padding: 0; font-size: $fs12; font-weight: 500; }
QPushButton[cls="link-muted"]:hover { color: $fg; }
QPushButton[cls="dashed"] { border: 1px dashed $line_strong; border-radius: 8px; background: transparent; color: $fg2; }
QPushButton[cls="dashed"]:hover { background: $surface3; }
QPushButton[cls="option"] { border: 1px solid $line; border-radius: 9px; background: $surface2; text-align: left; padding: 0; }
QPushButton[cls="option"]:checked { border-color: $accent_text; background: $accent_soft2; }
QPushButton[cls="option"]:hover:!checked { background: $surface3; }
QPushButton[cls="nav"] { border: 0; border-radius: 8px; background: transparent; color: $fg2; text-align: left; padding: 0 10px; }
QPushButton[cls="nav"]:hover { background: $surface3; }
QPushButton[cls="nav"]:checked { background: $surface3; color: $fg; font-weight: 600; }
QPushButton[cls="nav-accent"] { border: 0; border-radius: 8px; background: transparent; text-align: left; padding: 0; }
QPushButton[cls="nav-accent"]:hover:!checked { background: $surface3; }
QPushButton[cls="nav-accent"]:checked { background: $accent_soft; }
QPushButton[cls="row"] { border: 0; border-radius: 7px; background: transparent; text-align: left; padding: 0; }
QPushButton[cls="row"]:hover:!checked { background: $surface3; }
QPushButton[cls="row"]:checked { background: $accent_soft; }
QPushButton[cls="select"] { text-align: left; padding: 0; }
QPushButton[cls="segment"] { border: 0; border-radius: 5px; background: transparent; color: $fg3; font-size: $fs12; padding: 0 10px; }
QPushButton[cls="segment"]:checked { background: $surface3; color: $fg; }
QPushButton[cls="segment"]:hover:!checked { color: $fg; }
QPushButton[cls="file-chip"] { background: $surface3; border: 0; border-radius: 5px; padding: 0; text-align: left; }
QPushButton[cls="file-chip"]:hover { background: $line_strong; }
#FieldType { background: transparent; border: 0; border-radius: 5px; }
#FieldType:hover { background: $surface3; }
#SendButton { border-radius: 9px; }
#CancelSendButton { border: 1px solid $line_strong; border-radius: 9px; font-size: $fs13; font-weight: 600; }
#MethodButton { border: 0; border-right: 1px solid $line; border-radius: 0; border-top-left-radius: 8px; border-bottom-left-radius: 8px; background: transparent; }
#MethodButton:hover { background: $surface3; }
#SaveButton { border: 0; border-radius: 0; border-top-left-radius: 6px; border-bottom-left-radius: 6px; background: transparent; }
#SaveMenuButton { border: 0; border-left: 1px solid $line; border-radius: 0; border-top-right-radius: 6px; border-bottom-right-radius: 6px; background: transparent; padding: 0; }
#SaveButton:hover, #SaveMenuButton:hover { background: $surface3; }
#SaveGroup { border: 1px solid $line; border-radius: 7px; }
#EnvSelect { background: $surface; }

/* ---------- inputs ---------- */
QLineEdit { background: $surface2; border: 1px solid $line; border-radius: 7px; padding: 0 10px; font-size: $fs12_5; lineedit-password-character: 8226; selection-background-color: $selection; selection-color: $fg; }
QLineEdit:focus { border-color: $line_strong; }
QLineEdit[cls="dialog"] { border-color: $line_strong; border-radius: 8px; padding: 0 11px; font-size: $fs13; }
QLineEdit[cls="bare"] { background: transparent; border: 0; border-radius: 0; padding: 0 10px; }
QLineEdit[cls="title"] { background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 0 8px; font-size: $fs16; font-weight: 600; }
QLineEdit[cls="title"]:hover, QLineEdit[cls="title"]:focus { border-color: $line; }
QLineEdit[cls="inline"] { padding: 0 6px; border-color: $line_strong; border-radius: 5px; background: $surface2; }
QLineEdit[mono="true"], QPlainTextEdit[mono="true"] { font-family: $mono_family; font-size: $fs12; }
QFrame[cls="field"] { background: $bg; border: 1px solid $line; border-radius: 7px; }
QFrame[cls="field-strong"] { background: $surface2; border: 1px solid $line_strong; border-radius: 8px; }
QPlainTextEdit { background: $bg; border: 1px solid $line; border-radius: 8px; selection-background-color: $selection; selection-color: $fg; }
QPlainTextEdit[cls="plain"] { border: 0; border-radius: 0; }
QPlainTextEdit[cls="dialog"] { border-color: $line_strong; border-radius: 9px; padding: 8px; }
QPlainTextEdit[cls="url"] { background: transparent; border: 0; border-radius: 0; }

QCheckBox { spacing: 9px; font-size: $fs12_5; background: transparent; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid $line_strong; border-radius: 3px; background: $surface2; }
QCheckBox::indicator:checked { border-color: $accent_text; background: $accent_text; image: url($check_svg); }
QCheckBox::indicator:disabled { background: $surface3; }
QRadioButton { spacing: 6px; font-size: $fs12_5; color: $fg2; background: transparent; }
QRadioButton:checked { color: $fg; }
QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid $line_strong; border-radius: 8px; background: $surface2; }
QRadioButton::indicator:checked { border-color: $accent_text; image: url($radio_svg); }

/* ---------- frames ---------- */
#DialogCard { background: $surface; border: 1px solid $line_strong; border-radius: 12px; }
QFrame[cls="dialog-header"] { border-bottom: 1px solid $line; }
QFrame[cls="dialog-footer"] { background: $bg; border-top: 1px solid $line; border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; }
QFrame[cls="side-panel"] { background: $bg; border-right: 1px solid $line; }
QFrame[cls="side-panel-bl"] { background: $bg; border-right: 1px solid $line; border-bottom-left-radius: 11px; }
QFrame[cls="side-panel-full"] { background: $bg; border-right: 1px solid $line; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }
QFrame[cls="preview"] { background: $bg; }
QFrame[cls="preview-br"] { background: $bg; border-bottom-right-radius: 11px; }
QFrame[cls="table"] { border: 1px solid $line; border-radius: 8px; background: $surface; }
QFrame[cls="table-flat"] { border: 1px solid $line; border-radius: 8px; background: transparent; }
QFrame[cls="table-head"] { background: $bg; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QFrame[cls="table-row"] { border-top: 1px solid $line; background: transparent; }
QFrame[cls="table-row-first"] { background: transparent; }
QFrame[cls="table-row-muted"] { border-top: 1px solid $line; background: $bg; }
QWidget[cls="cell"], QLabel[cls="cell"], QLineEdit[cls="cell"] { border: 0; border-right: 1px solid $line; border-radius: 0; background: transparent; }
QLabel[cls="cell-head"] { color: $fg3; font-size: $fs11_5; font-weight: 500; padding: 0 10px; }
QFrame[cls="dashed-box"] { border: 1px dashed $line_strong; border-radius: 8px; background: transparent; }
QFrame[cls="drop-zone"] { border: 1px dashed $line_strong; border-radius: 12px; background: $bg; }
QFrame[cls="drop-zone-active"] { border: 1px dashed $accent_text; border-radius: 12px; background: $accent_soft2; }
QFrame[cls="card"] { border: 1px solid $line_strong; border-radius: 10px; background: $surface2; }
QFrame[cls="note"] { border: 1px solid $line; border-radius: 9px; background: $bg; }
QFrame[cls="segmented"] { background: $bg; border: 1px solid $line; border-radius: 7px; }
QFrame[cls="segmented-lg"] { background: $bg; border: 1px solid $line; border-radius: 8px; }
QFrame[cls="separator-v"] { background: $line; max-width: 1px; min-width: 1px; }
QFrame[cls="hline"] { background: $line; border: 0; }
QScrollArea[cls="form-pane"] { border: 0; border-right: 1px solid $line; }
QFrame[cls="bar"] { border-bottom: 1px solid $line; }
QFrame[cls="setting-row"] { border-bottom: 1px solid $line; }
#UrlBar { background: $surface2; border: 1px solid $line_strong; border-radius: 9px; }
#Popover { background: $surface2; border: 1px solid $line_strong; border-radius: 9px; }
#QuickLook { background: $surface2; border: 1px solid $line_strong; border-radius: 10px; }
#QuickLookHeader { border-bottom: 1px solid $line; }
#ResolvePopup { background: $surface2; border: 1px solid $line_strong; border-radius: 7px; }
#Toast { background: $surface2; border: 1px solid $line_strong; border-radius: 10px; }
#FindBar { border-top: 1px solid $line; background: $surface; }
#BodyFrame { border-top: 1px solid $line; background: $bg; }
#HeadersTable { background: transparent; border: 1px solid $line; border-radius: 8px; selection-background-color: $selection; selection-color: $fg; }
#HeadersTable::item { padding: 6px 10px; border-top: 1px solid $line; color: $fg; }
#HeadersTable QHeaderView::section { background: $bg; color: $fg3; border: 0; padding: 0 12px; }
#HeadersTable QHeaderView { background: transparent; border-top-left-radius: 7px; border-top-right-radius: 7px; }

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $line_strong; border-radius: 2px; min-height: 28px; margin: 3px; }
QScrollBar::handle:horizontal { background: $line_strong; border-radius: 2px; min-width: 28px; margin: 3px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMenu { background: $surface2; border: 1px solid $line_strong; padding: 4px; }
QMenu::item { padding: 6px 14px; border-radius: 5px; font-size: $fs12_5; }
QMenu::item:selected { background: $surface3; }
QMenu::separator { height: 1px; background: $line; margin: 4px 2px; }
""")


def build_style_sheet(t: Theme) -> str:
    values = {name: qss_color(color) for name, color in t.colors.items()}
    disabled = QColor(t.c("accent"))
    disabled.setAlphaF(0.45)
    values["accent_disabled"] = qss_color(disabled)
    on_disabled = t.c("on_accent")
    on_disabled.setAlphaF(0.6)
    values["on_accent_disabled"] = qss_color(on_disabled)
    values["mono_family"] = css_families(mono=True)
    for px in _SIZES:
        values["fs" + str(px).replace(".", "_")] = f"{px_to_pt(px):.2f}pt"
    check = icons.svg("check", t.c("on_check").name(), stroke=3.2)
    values["check_svg"] = icons.svg_file(check)
    dot = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14">'
           f'<circle cx="7" cy="7" r="3.5" fill="{t.c("accent_text").name()}"/></svg>')
    values["radio_svg"] = icons.svg_file(dot)
    return STYLE_SHEET.substitute(values)


def set_cls(widget: QWidget, cls: str) -> QWidget:
    """Assign a style class (matched by [cls="..."] selectors).

    Only widgets that are already polished get re-polished. Polishing a widget before it is shown makes
    the style-sheet engine remember the default font and restore it on first show, which would discard a
    font set with setFont() in between.
    """
    widget.setProperty("cls", cls)
    if widget.testAttribute(Qt.WidgetAttribute.WA_WState_Polished):
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
    return widget
