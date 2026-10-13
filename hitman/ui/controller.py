"""User actions: sending, saving, menus and dialogs. Keeps MainWindow focused on layout."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QFileDialog, QWidget

from hitman.core.curl import CurlParseError, parse_curl
from hitman.core.formatting import detect_format, extension_for, slug
from hitman.core.http import HttpResponse
from hitman.core.models import Request, Variable, count_requests
from hitman.paths import display_path
from hitman.ui.dialogs.code_dialog import CodeDialog
from hitman.ui.dialogs.collection_dialog import CollectionDialog
from hitman.ui.dialogs.confirm import ConfirmDialog, confirm
from hitman.ui.dialogs.environments_dialog import EnvironmentsDialog
from hitman.ui.dialogs.export_dialog import ExportDialog
from hitman.ui.dialogs.import_dialog import ImportDialog
from hitman.ui.dialogs.save_request import SaveRequestDialog
from hitman.ui.dialogs.settings_dialog import SettingsDialog
from hitman.ui.sidebar.collections_panel import TreeRow
from hitman.ui.theme import manager
from hitman.ui.widgets.common import ColorDot, ElidedLabel, RoleLabel, button, hbox, label, vbox
from hitman.ui.widgets.popover import FloatingPanel, PopoverMenu

if TYPE_CHECKING:
    from hitman.ui.main_window import MainWindow

MASK = "••••••••••"


class Controller:
    def __init__(self, window: MainWindow):
        self.w = window
        self.ws = window.workspace
        self.session = window.session
        self._code_language = "curl"

    # ================================================================ send
    def send(self) -> None:
        tab = self.session.active
        if tab.loading:
            return
        if not tab.request.url.strip():
            self.w.notify("Enter a URL first", "The request needs a URL before it can be sent", error=True)
            return
        self.session.set_loading(tab.id, True)
        self.w.runner.send(tab.id, self.w.resolve(tab), self.ws.settings.send_options())

    def on_response(self, tab_id: str, response: HttpResponse) -> None:
        tab = self.session.tab(tab_id)
        if tab is None:
            return
        self.session.set_response(tab_id, response)
        self.ws.record_history(tab.request, response, tab.request.id if tab.saved else None)

    def cancel(self) -> None:
        tab = self.session.active
        if tab.loading:
            self.w.runner.cancel(tab.id)
            self.session.set_loading(tab.id, False)
            self.w.notify("Request cancelled")

    # ================================================================ tabs
    def new_tab(self) -> None:
        self.session.new_tab()
        self.w.request_panel.focus_url()

    def open_request(self, request_id: str) -> None:
        request = self.ws.saved_request(request_id)
        if request:
            self.session.open_saved(request, replace_clean_active=not self.ws.settings.open_in_new_tab)

    def open_history(self, entry) -> None:
        self.session.open_draft(entry.request, replace_clean_active=not self.ws.settings.open_in_new_tab)

    def close_tab(self, tab_id: str) -> None:
        tab = self.session.tab(tab_id)
        if tab is None:
            return
        if tab.dirty and self.ws.settings.ask_before_close:
            dialog = ConfirmDialog(self.w, "Save changes?",
                                   f"“{tab.request.name}” has unsaved changes. Save them before closing?",
                                   [("discard", "Don't save", "secondary"), ("cancel", "Cancel", "secondary"),
                                    ("save", "Save", "primary")])
            dialog.exec()
            if dialog.choice in (None, "cancel"):
                return
            if dialog.choice == "save":
                self.session.set_active(tab_id)
                if not self.save():
                    return
        self.w.runner.cancel(tab_id)
        self.session.close(tab_id)

    def confirm_quit(self) -> bool:
        if self.ws.settings.restore_tabs or not any(t.dirty for t in self.session.tabs):
            return True
        return confirm(self.w, "Quit with unsaved changes?",
                       "Some tabs have changes that aren't saved. They will be lost.", "Quit")

    def paste_curl(self, text: str) -> None:
        try:
            parsed = parse_curl(text)
        except CurlParseError as exc:
            self.w.notify("Couldn't read that cURL command", str(exc), error=True)
            return
        tab = self.session.active
        keep_id, keep_name = tab.request.id, tab.request.name
        tab.request = parsed
        tab.request.id = keep_id
        if tab.saved or keep_name != Request().name:
            tab.request.name = keep_name
        self.session.touch(tab.id)  # the window re-binds because the request object changed
        self.w.notify("Imported cURL command", f"{parsed.method} {parsed.url}")

    # ================================================================ save
    def save(self) -> bool:
        tab = self.session.active
        if not tab.saved:
            return self.save_as()
        self.ws.update_request(tab.request)
        self.session.mark_saved(tab.id, tab.request)
        location = self.ws.locate(tab.request.id)
        crumbs = " / ".join((location.breadcrumb if location else []) + [tab.request.name])
        self.w.notify("Request saved", crumbs)
        return True

    def save_as(self, save_as: bool = False) -> bool:
        tab = self.session.active
        location = self.ws.locate(tab.request.id) if tab.saved else None
        dialog = SaveRequestDialog(self.w, self.ws.collections, tab.request.name, save_as=save_as,
                                   collection_id=location.collection.id if location else None,
                                   folder_id=location.parent_id if location else None)
        if not dialog.exec() or dialog.result_target is None:
            return False
        target = dialog.result_target
        collection_id = target.collection_id
        if target.new_collection:
            collection_id = self.ws.create_collection(target.new_collection, auth_type="none").id
        parent_id = target.folder_id
        if target.new_folder:
            parent_id = self.ws.add_folder(collection_id, parent_id, target.new_folder).id
        request = tab.request.copy()
        request.name = target.name
        if tab.saved:  # "Save as" creates a copy; the original stays as it was
            request.id = Request().id
        self.ws.add_request(collection_id, parent_id, request)
        self.session.mark_saved(tab.id, request)
        self.w.collections_panel.expand(collection_id, parent_id)
        crumbs = " / ".join(self.ws.locate(request.id).breadcrumb + [request.name])
        self.w.notify("Request saved", crumbs)
        return True

    def save_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self.w)
        menu.add_item("Save as…", lambda: self.save_as(save_as=True))
        menu.add_item("Revert changes", self.revert)
        menu.show_at(anchor, align="right", width=190)

    def revert(self) -> None:
        tab = self.session.active
        if not tab.saved:
            self.w.notify("Nothing to revert", "This request has not been saved yet")
            return
        self.session.revert(tab.id)

    def save_response(self) -> None:
        tab = self.session.active
        response = tab.response
        if not response or not response.ok:
            return
        fmt = detect_format(response.content_type, response.body)
        downloads = Path.home() / "Downloads"
        default = (downloads if downloads.is_dir() else Path.home()) / f"{slug(tab.request.name)}-response.{extension_for(fmt)}"
        path, _ = QFileDialog.getSaveFileName(self.w, "Save response", str(default))
        if not path:
            return
        try:
            Path(path).write_bytes(response.body)
        except OSError as exc:
            self.w.notify("Couldn't save the response", str(exc.strerror or exc), error=True)
            return
        self.w.notify("Response saved", display_path(path))

    # ========================================================= collections
    def new_collection(self) -> None:
        dialog = CollectionDialog(self.w)
        accepted = dialog.exec()
        if dialog.switch_to_import:
            self.import_data()
            return
        if not accepted or dialog.result_form is None:
            return
        form = dialog.result_form
        collection = self.ws.create_collection(form.name, form.base_url, auth=form.auth)
        self.w.collections_panel.expand(collection.id)
        self.w.show_section("collections")
        self.w.notify("Collection created", collection.name)

    def edit_collection(self, collection_id: str) -> None:
        collection = self.ws.collection(collection_id)
        if collection is None:
            return
        dialog = CollectionDialog(self.w, collection)
        if not dialog.exec() or dialog.result_form is None:
            return
        form = dialog.result_form
        variables = [v for v in collection.variables if v.key != "baseUrl"]
        if form.base_url:
            variables.insert(0, Variable(key="baseUrl", value=form.base_url))
        self.ws.update_collection(collection_id, name=form.name, auth=form.auth, variables=variables)
        self.w.notify("Collection updated", form.name)

    def import_data(self) -> None:
        dialog = ImportDialog(self.w)
        if not dialog.exec() or dialog.result is None:
            return
        result = dialog.result
        if result.request is not None:
            self.session.open_draft(result.request)
            self.w.notify("Imported cURL command", f"{result.request.method} {result.request.url}")
            return
        self.ws.add_collection(result.collection)
        self.w.collections_panel.expand(result.collection.id)
        self.w.show_section("collections")
        count = result.request_count
        self.w.notify("Import complete", f"{result.collection.name} · {count} request{'s' if count != 1 else ''}")

    def export_data(self, collection_id: str | None = None) -> None:
        if not self.ws.collections:
            self.w.notify("Nothing to export", "Create or import a collection first")
            return
        if collection_id is None:
            active = self.session.active
            collection = self.w.collection_for(active)
            collection_id = collection.id if collection else None
        env = self.ws.active_environment
        env_vars = [v for v in env.variables if v.enabled and not v.secret] if env else []
        dialog = ExportDialog(self.w, self.ws.collections, collection_id, env_vars)
        if dialog.exec() and dialog.exported_path:
            self.w.notify("Collection exported", display_path(dialog.exported_path))

    def rename_node(self, node_id: str, name: str) -> None:
        self.ws.rename(node_id, name)

    def node_menu(self, row: TreeRow, anchor: QRect) -> None:
        menu = PopoverMenu(self.w)
        if row.kind == "collection":
            menu.add_item("Add request", lambda: self.add_request(row.collection_id, None))
            menu.add_item("Add folder", lambda: self.add_folder(row.collection_id, None))
            menu.add_separator()
            menu.add_item("Rename", lambda: self.w.collections_panel.view.start_rename(row.id))
            menu.add_item("Edit…", lambda: self.edit_collection(row.id))
            menu.add_item("Export…", lambda: self.export_data(row.id))
            menu.add_item("Duplicate", lambda: self.duplicate_collection(row.id))
            menu.add_separator()
            menu.add_item("Delete", lambda: self.delete_node(row), role="err")
        elif row.kind == "folder":
            menu.add_item("Add request", lambda: self.add_request(row.collection_id, row.id))
            menu.add_item("Add folder", lambda: self.add_folder(row.collection_id, row.id))
            menu.add_separator()
            menu.add_item("Rename", lambda: self.w.collections_panel.view.start_rename(row.id))
            menu.add_separator()
            menu.add_item("Delete", lambda: self.delete_node(row), role="err")
        else:
            menu.add_item("Open in tab", lambda: self.open_request(row.id))
            menu.add_item("Rename", lambda: self.w.collections_panel.view.start_rename(row.id))
            menu.add_item("Duplicate", lambda: self.duplicate_request(row.id))
            menu.add_separator()
            menu.add_item("Delete", lambda: self.delete_node(row), role="err")
        menu.destroyed.connect(self.w.collections_panel.view.menu_closed)
        menu.show_at(anchor, align="right" if anchor.width() > 1 else "left", width=190)

    def add_request(self, collection_id: str, parent_id: str | None) -> None:
        collection = self.ws.collection(collection_id)
        has_base = collection and any(v.key == "baseUrl" for v in collection.variables)
        request = Request(name="New request", url="{{baseUrl}}/" if has_base else "")
        self.ws.add_request(collection_id, parent_id, request)
        self.w.collections_panel.expand(collection_id, parent_id)
        self.open_request(request.id)
        self.w.request_panel.focus_url()

    def add_folder(self, collection_id: str, parent_id: str | None) -> None:
        folder = self.ws.add_folder(collection_id, parent_id)
        self.w.collections_panel.expand(collection_id, parent_id)
        self.w.collections_panel.view.start_rename(folder.id)

    def duplicate_collection(self, collection_id: str) -> None:
        copy = self.ws.duplicate_collection(collection_id)
        if copy:
            self.w.notify("Collection duplicated", copy.name)

    def duplicate_request(self, request_id: str) -> None:
        location = self.ws.locate(request_id)
        if location is None or not isinstance(location.node, Request):
            return
        copy = location.node.copy()
        copy.id = Request().id
        copy.name = f"{copy.name} copy"
        self.ws.add_request(location.collection.id, location.parent_id, copy, after_id=request_id)
        self.open_request(copy.id)

    def delete_node(self, row: TreeRow) -> None:
        location = self.ws.locate(row.id)
        if location is None:
            return
        if row.kind == "collection":
            count = count_requests(location.collection.items)
            if not confirm(self.w, "Delete collection?",
                           f"“{row.name}” and its {count} request{'s' if count != 1 else ''} will be deleted. "
                           "This can't be undone.", "Delete"):
                return
            self.ws.delete_collection(row.id)
        elif row.kind == "folder":
            count = count_requests(location.node.items)
            if not confirm(self.w, "Delete folder?",
                           f"“{row.name}” and its {count} request{'s' if count != 1 else ''} will be deleted. "
                           "This can't be undone.", "Delete"):
                return
            self.ws.delete_item(row.id)
        else:
            self.ws.delete_item(row.id)
        self.w.notify("Deleted", row.name)

    def clear_history(self) -> None:
        if confirm(self.w, "Clear history?", "Every entry in your request history will be removed.", "Clear"):
            self.ws.clear_history()

    # ======================================================== environments
    def environment_menu(self, anchor: QWidget) -> None:
        menu = PopoverMenu(self.w)
        menu.add_header("Environment")
        active = self.ws.active_env_id
        menu.add_item("No environment", lambda: self.ws.set_active_environment(None), checked=active is None,
                      role="fg2")
        for env in self.ws.environments:
            if not env.is_global:
                menu.add_item(env.name, lambda e=env.id: self.ws.set_active_environment(e), dot=env.color,
                              checked=env.id == active)
        menu.add_separator()
        menu.add_item("Manage environments…", self.manage_environments)
        menu.show_at(anchor, align="right", width=220)

    def manage_environments(self, create: bool = False) -> None:
        dialog = EnvironmentsDialog(self.w, self.ws.environments, self.ws.active_env_id, create=create)
        if dialog.exec():
            self.ws.save_environments(dialog.environments, dialog.active_id)
            count = len(dialog.environments)
            self.w.notify("Environments saved", f"{count} environment{'s' if count != 1 else ''}")

    def quick_look(self, anchor: QWidget) -> None:
        panel = FloatingPanel(self.w, object_name="QuickLook", margins=(0, 0, 0, 6))
        env = self.ws.active_environment
        header = QWidget()
        header.setObjectName("QuickLookHeader")
        head = hbox(header, (14, 12, 14, 12), 8)
        head.addWidget(ColorDot(env.color if env else "fg3", 8))
        head.addWidget(RoleLabel(env.name if env else "No environment", "fg", px=12.5, weight=600), 1)

        def edit() -> None:
            panel.close()
            self.manage_environments()

        head.addWidget(button("Edit", "link", on_click=edit))
        panel.body.addWidget(header)
        rows = vbox(margins=(0, 6, 0, 0))
        variables = [v for v in (env.variables if env else []) if v.key]
        for var in variables:
            line = hbox(margins=(14, 6, 14, 6), spacing=10)
            key = ElidedLabel(var.key, "fg2", px=11.5, mono=True)
            key.setFixedWidth(120)
            line.addWidget(key)
            value = (MASK if var.value else "—") if var.secret else (var.value or "—")
            line.addWidget(ElidedLabel(value, "fg", px=11.5, mono=True), 1)
            rows.addLayout(line)
        if not variables:
            empty = label("Pick an environment to see its variables." if env is None else "No variables yet.", "hint")
            empty.setContentsMargins(14, 8, 14, 8)
            rows.addWidget(empty)
        panel.body.addLayout(rows)
        panel.show_at(anchor, align="right", width=380)

    # ============================================================= dialogs
    def open_code(self) -> None:
        dialog = CodeDialog(self.w, self.w.resolve(self.session.active), self._code_language)
        dialog.exec()
        self._code_language = dialog.language

    def open_settings(self, section: str = "general") -> None:
        SettingsDialog(self.w, self.ws, section if isinstance(section, str) else "general").exec()

    def toggle_theme(self) -> None:
        self.ws.update_settings(theme="light" if manager().theme.dark else "dark")

    def toggle_layout(self) -> None:
        side = self.ws.settings.layout == "side-by-side"
        self.ws.update_settings(layout="stacked" if side else "side-by-side")
