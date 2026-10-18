"""Main window: assembles the layout and keeps it in sync with the workspace and session."""

from __future__ import annotations

import warnings

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QMainWindow, QStackedWidget, QWidget

from hitman import APP_NAME
from hitman.core.http import ResolvedRequest, resolve_request
from hitman.core.models import AUTH_LABELS, Collection
from hitman.services.runner import RequestRunner
from hitman.services.session import OpenTab, Session
from hitman.services.workspace import Workspace
from hitman.ui import native
from hitman.ui.controller import Controller
from hitman.ui.rail import Rail
from hitman.ui.request.request_panel import RequestPanel
from hitman.ui.request.tab_strip import TabStrip
from hitman.ui.shortcuts import SHORTCUTS, qt_sequence
from hitman.ui.sidebar.collections_panel import CollectionsPanel
from hitman.ui.sidebar.environments_panel import EnvironmentsPanel
from hitman.ui.sidebar.history_panel import HistoryPanel
from hitman.ui.status_bar import StatusBar
from hitman.ui.theme import manager
from hitman.ui.title_bar import TRAFFIC_LIGHTS_INSET, TitleBar
from hitman.ui.widgets.common import hbox, vbox
from hitman.ui.widgets.toast import Toast

SECTION_INDEX = {"collections": 0, "environments": 1, "history": 2}


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.session = Session(self)
        self.runner = RequestRunner(self)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(980, 620)
        custom_controls, inset = self._setup_frame()

        root = QWidget()
        root.setObjectName("Root")
        _ignore_safe_area(root)
        self.setCentralWidget(root)
        layout = vbox(root)
        self.title_bar = TitleBar(custom_controls=custom_controls, left_inset=inset)
        layout.addWidget(self.title_bar)

        work = hbox()
        self.rail = Rail()
        work.addWidget(self.rail)
        self.sidebar = QStackedWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(260)
        self.collections_panel = CollectionsPanel()
        self.environments_panel = EnvironmentsPanel()
        self.history_panel = HistoryPanel()
        for panel in (self.collections_panel, self.environments_panel, self.history_panel):
            self.sidebar.addWidget(panel)
        work.addWidget(self.sidebar)

        main = QFrame()
        main.setObjectName("MainColumn")
        main_layout = vbox(main)
        self.tab_strip = TabStrip()
        main_layout.addWidget(self.tab_strip)
        self.request_panel = RequestPanel(self.active_scope, self.resolve)
        main_layout.addWidget(self.request_panel, 1)
        work.addWidget(main, 1)
        layout.addLayout(work, 1)
        self.status_bar = StatusBar()
        layout.addWidget(self.status_bar)
        self.toast = Toast(root)

        self.controller = Controller(self)
        self._shown_once = False
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(800)
        self._persist_timer.timeout.connect(self.persist_session)
        self._split_timer = QTimer(self)
        self._split_timer.setSingleShot(True)
        self._split_timer.setInterval(400)
        self._split_timer.timeout.connect(
            lambda: self.workspace.set_ui_state("split", self.request_panel.split_ratios()))
        self._connect()
        self._install_shortcuts()
        self._restore()

    # -------------------------------------------------------------- frame
    def _setup_frame(self) -> tuple[bool, int]:
        """macOS keeps its native window buttons inside our title bar; Windows and Linux get our own."""
        self._mac_expanded = False
        if native.IS_MAC:
            if not hasattr(Qt.WindowType, "ExpandedClientAreaHint"):  # Qt < 6.9: keep the standard title bar
                return False, 0
            with warnings.catch_warnings():
                # PySide reports this flag under a deprecated alias that shares its value; it's not deprecated.
                warnings.simplefilter("ignore", DeprecationWarning)
                self.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint, True)
            self.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint, True)
            _ignore_safe_area(self)
            self._mac_expanded = True
            return False, TRAFFIC_LIGHTS_INSET
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowMinMaxButtonsHint)
        self._resizer = _EdgeResizer(self)
        QApplication.instance().installEventFilter(self._resizer)
        return True, 0

    def _sync_mac_title_bar(self) -> None:
        """Fit the title bar around the traffic lights; full screen hides them, so use the full design."""
        handle = self.windowHandle()
        if not self._mac_expanded or handle is None:
            return
        native.hide_native_title(self)
        top = handle.safeAreaMargins().top() if hasattr(handle, "safeAreaMargins") else 0
        if top >= 24 and not self.isFullScreen():
            self.title_bar.setFixedHeight(top)
            right = native.traffic_lights_right_edge(self)
            self.title_bar.set_left_inset(right + 4 if right else TRAFFIC_LIGHTS_INSET)
        else:
            self.title_bar.setFixedHeight(TitleBar.HEIGHT)
            self.title_bar.set_left_inset(0)

    def _sync_frame_border(self) -> None:
        """Frameless windows get a hairline border so their edge is visible, except when maximized."""
        root = self.centralWidget()
        framed = bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint) and not (
            self.isMaximized() or self.isFullScreen())
        if root is not None and root.property("framed") != framed:
            root.setProperty("framed", framed)
            root.style().unpolish(root)
            root.style().polish(root)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_frame_border()
            QTimer.singleShot(0, self._sync_mac_title_bar)

    # ------------------------------------------------------------- wiring
    def _connect(self) -> None:
        ws, c = self.workspace, self.controller
        ws.collections_changed.connect(self._on_collections_changed)
        ws.environments_changed.connect(self._on_environments_changed)
        ws.active_environment_changed.connect(self._on_environments_changed)
        ws.history_changed.connect(lambda: self.history_panel.set_entries(ws.history()))
        ws.settings_changed.connect(self._apply_settings)

        self.session.tabs_changed.connect(self._render_tabs)
        self.session.tab_updated.connect(self._on_tab_updated)
        self.runner.finished.connect(c.on_response)

        self.title_bar.toggle_theme.connect(c.toggle_theme)
        self.title_bar.open_settings.connect(c.open_settings)
        self.rail.section_clicked.connect(self._on_rail)
        self.rail.open_settings.connect(c.open_settings)
        self.status_bar.toggle_layout.connect(c.toggle_layout)

        cp = self.collections_panel
        cp.new_collection.connect(c.new_collection)
        cp.import_clicked.connect(c.import_data)
        cp.export_clicked.connect(c.export_data)
        cp.open_request.connect(c.open_request)
        cp.menu_requested.connect(c.node_menu)
        cp.rename_requested.connect(c.rename_node)
        cp.expanded_changed.connect(lambda ids: ws.set_ui_state("expanded", ids))
        self.environments_panel.activate.connect(ws.set_active_environment)
        self.environments_panel.manage.connect(c.manage_environments)
        self.history_panel.open_entry.connect(c.open_history)
        self.history_panel.clear.connect(c.clear_history)

        ts = self.tab_strip
        ts.tab_picked.connect(self.session.set_active)
        ts.tab_close.connect(c.close_tab)
        ts.new_tab.connect(c.new_tab)
        ts.env_menu.connect(c.environment_menu)
        ts.quick_look.connect(c.quick_look)

        rp = self.request_panel
        rp.draft_changed.connect(self.session.touch)
        rp.send.connect(c.send)
        rp.cancel.connect(c.cancel)
        rp.save.connect(c.save)
        rp.save_menu.connect(c.save_menu)
        rp.open_code.connect(c.open_code)
        rp.curl_pasted.connect(c.paste_curl)
        rp.notify.connect(lambda title, sub, error: self.notify(title, sub, error=error))
        rp.save_response.connect(c.save_response)
        rp.split_changed.connect(lambda _ratios: self._split_timer.start())

    def _install_shortcuts(self) -> None:
        c = self.controller
        handlers = {
            "send": c.send, "new": c.new_tab, "save": c.save, "close": lambda: c.close_tab(self.session.active_id),
            "search": self._focus_search, "import": c.import_data, "sidebar": self.toggle_sidebar,
            "code": c.open_code, "settings": c.open_settings, "next_tab": lambda: self.session.cycle(1),
            "prev_tab": lambda: self.session.cycle(-1), "shortcuts": lambda: c.open_settings("shortcuts"),
        }
        for action, _label, sequence in SHORTCUTS:
            shortcut = QShortcut(QKeySequence(qt_sequence(sequence)), self)
            shortcut.activated.connect(handlers[action])
        QShortcut(QKeySequence("Ctrl+Enter"), self).activated.connect(c.send)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.request_panel.focus_url)

    # ------------------------------------------------------------ restore
    def _restore(self) -> None:
        ws = self.workspace
        self.collections_panel.expanded = set(ws.ui_state("expanded", []))
        self.request_panel.set_split_ratios(ws.ui_state("split", {}))
        geometry = ws.ui_state("geometry")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        else:
            self.resize(1440, 900)
        if ws.settings.restore_tabs:
            self.session.restore(ws.ui_state("session"), ws.saved_request)
        self._on_collections_changed()
        self._on_environments_changed()
        self.history_panel.set_entries(ws.history())
        self._apply_settings()
        self._render_tabs()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            handle = self.windowHandle()
            if self._mac_expanded and handle is not None and hasattr(handle, "safeAreaMarginsChanged"):
                handle.safeAreaMarginsChanged.connect(self._sync_mac_title_bar)
            self._sync_mac_title_bar()
            self._sync_frame_border()
            QTimer.singleShot(0, self.request_panel.apply_split)

    def persist_session(self) -> None:
        if self.workspace.settings.restore_tabs:
            self.workspace.set_ui_state("session", self.session.to_state())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.controller.confirm_quit():
            event.ignore()
            return
        self.workspace.set_ui_state("geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.persist_session()
        super().closeEvent(event)

    # ------------------------------------------------------------- helpers
    def notify(self, title: str, sub: str = "", *, error: bool = False) -> None:
        self.toast.show_message(title, sub, error=error)

    def collection_for(self, tab: OpenTab) -> Collection | None:
        if not tab.saved:
            return None
        location = self.workspace.locate(tab.request.id)
        return location.collection if location else None

    def active_scope(self) -> dict[str, str]:
        return self.workspace.variable_scope(self.collection_for(self.session.active))

    def resolve(self, tab: OpenTab) -> ResolvedRequest:
        collection = self.collection_for(tab)
        scope = self.workspace.variable_scope(collection)
        return resolve_request(tab.request, scope, collection.auth if collection else None)

    def breadcrumb(self, tab: OpenTab) -> list[str]:
        if not tab.saved:
            return []
        location = self.workspace.locate(tab.request.id)
        return location.breadcrumb if location else []

    def inherit_html(self, tab: OpenTab) -> str:
        collection = self.collection_for(tab)
        if collection is None:
            return "This request isn't saved in a collection yet, so there is no auth to inherit."
        if collection.auth.type in ("none", "inherit"):
            return f"Its collection, <b>{collection.name}</b>, doesn't use any authorization."
        return (f"This request uses <b>{AUTH_LABELS[collection.auth.type]}</b> auth from its collection, "
                f"<b>{collection.name}</b>.")

    # ----------------------------------------------------------- rendering
    def _render_tabs(self) -> None:
        active = self.session.active
        self.tab_strip.set_tabs(self.session.tabs, active.id)
        self.request_panel.bind(active, self.breadcrumb(active), self.inherit_html(active))
        self.collections_panel.set_active_request(active.request.id if active.saved else None)
        self._persist_timer.start()

    def _on_tab_updated(self, tab_id: str) -> None:
        tab = self.session.tab(tab_id)
        if tab is None:
            return
        active = tab_id == self.session.active_id
        self.tab_strip.update_tab(tab, active)
        if active:
            self.request_panel.refresh_status(self.breadcrumb(tab))
            if self.request_panel.tab is not tab or self.request_panel.editor.request is not tab.request:
                self.request_panel.bind(tab, self.breadcrumb(tab), self.inherit_html(tab))
        self._persist_timer.start()

    def _on_collections_changed(self) -> None:
        self.collections_panel.set_collections(self.workspace.collections)
        self.session.sync_saved(self.workspace.saved_request)
        active = self.session.active
        self.request_panel.refresh_status(self.breadcrumb(active))
        self.request_panel.editor.set_inherit_text(self.inherit_html(active))
        self.request_panel.refresh_derived()

    def _on_environments_changed(self) -> None:
        env = self.workspace.active_environment
        name, color = (env.name, env.color) if env else ("No environment", "fg3")
        self.tab_strip.set_environment(name, color)
        self.status_bar.set_environment(name, color)
        self.environments_panel.set_environments(self.workspace.environments, self.workspace.active_env_id)
        self.request_panel.refresh_derived()

    def _apply_settings(self) -> None:
        s = self.workspace.settings
        manager().configure(s.theme, s.font_size)
        side = s.layout == "side-by-side"
        self.request_panel.set_layout(side)
        self.status_bar.set_layout(side)
        self.status_bar.set_ssl(s.verify_ssl)
        self.sidebar.setVisible(s.sidebar_visible)
        self.sidebar.setCurrentIndex(SECTION_INDEX.get(s.sidebar_section, 0))
        self.rail.set_state(s.sidebar_section, s.sidebar_visible)
        self.request_panel.refresh_derived()

    # ------------------------------------------------------------- sidebar
    def _on_rail(self, section: str) -> None:
        s = self.workspace.settings
        visible = not s.sidebar_visible if section == s.sidebar_section else True
        self.workspace.update_settings(sidebar_section=section, sidebar_visible=visible)

    def show_section(self, section: str) -> None:
        self.workspace.update_settings(sidebar_section=section, sidebar_visible=True)

    def toggle_sidebar(self) -> None:
        self.workspace.update_settings(sidebar_visible=not self.workspace.settings.sidebar_visible)

    def _focus_search(self) -> None:
        self.show_section("collections")
        self.collections_panel.focus_filter()


def _ignore_safe_area(widget: QWidget) -> None:
    """Lay out under the macOS title bar instead of below it (Qt 6.9+)."""
    attribute = getattr(Qt.WidgetAttribute, "WA_ContentsMarginsRespectsSafeArea", None)
    if attribute is not None:
        widget.setAttribute(attribute, False)


class _EdgeResizer(QObject):
    """Lets a frameless window be resized from its edges (Windows/Linux)."""

    MARGIN = 6

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.window = window
        self._cursor_set = False

    def _edges(self, global_pos: QPoint) -> Qt.Edge:
        if self.window.isMaximized() or self.window.isFullScreen():
            return Qt.Edge(0)
        geo = self.window.frameGeometry()
        x, y, m = global_pos.x(), global_pos.y(), self.MARGIN
        edges = Qt.Edge(0)
        if x - geo.left() < m:
            edges |= Qt.Edge.LeftEdge
        elif geo.right() - x < m:
            edges |= Qt.Edge.RightEdge
        if y - geo.top() < m:
            edges |= Qt.Edge.TopEdge
        elif geo.bottom() - y < m:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor(edges: Qt.Edge) -> Qt.CursorShape:
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            main_diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
            return Qt.CursorShape.SizeFDiagCursor if main_diagonal else Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.HoverMove):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.window:
            return False
        global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else None
        if global_pos is None:
            return False
        edges = self._edges(global_pos)
        if edges:
            if not self._cursor_set:
                QApplication.setOverrideCursor(self._cursor(edges))
                self._cursor_set = True
            else:
                QApplication.changeOverrideCursor(self._cursor(edges))
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.window.windowHandle().startSystemResize(edges)
                return True
        elif self._cursor_set:
            QApplication.restoreOverrideCursor()
            self._cursor_set = False
        return False
