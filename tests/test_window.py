"""End-to-end checks on the real main window, run offscreen."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hitman.core.models import Auth, Collection, Environment, KeyValue, Request, Variable  # noqa: E402
from hitman.core.urls import apply_url  # noqa: E402


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path, "auth": self.headers.get("Authorization")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.dumps({"type": self.headers.get("Content-Type", "").split(";")[0],
                              "has_file": b'filename="note.txt"' in body and b"hello file" in body}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("HITMAN_HOME", str(tmp_path))
    from hitman.app import create_app
    from hitman.paths import database_path
    from hitman.services.workspace import Workspace
    from hitman.storage.database import Database
    from hitman.ui.fonts import load_fonts
    from hitman.ui.main_window import MainWindow
    from hitman.ui.theme import ThemeManager

    app = QApplication.instance() or create_app([])
    load_fonts()
    ws = Workspace(Database(database_path()))
    ThemeManager(app).configure("dark", 13)
    win = MainWindow(ws)
    win.resize(1280, 800)
    win.show()
    _wait(50)
    yield win
    win.close()
    ws.db.close()


def _with_dialog(action, interact):
    """Run `action`, which opens a modal dialog, and drive the dialog once it is showing."""
    def poke():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(20, poke)
        else:
            interact(dialog)
    QTimer.singleShot(20, poke)
    return action()


def test_send_resolves_variables_auth_and_records_history(window, server):
    ws = window.workspace
    request = Request(name="Get user")
    apply_url(request, "{{baseUrl}}/users/:id")
    request.path_vars[0].value = "{{userId}}"
    collection = Collection(name="Local", auth=Auth.with_variables("bearer"),
                            variables=[Variable("baseUrl", server)], items=[request])
    ws.add_collection(collection)
    ws.save_environments(ws.environments + [Environment(id="dev", name="Dev", variables=[
        Variable("userId", "42"), Variable("accessToken", "tok", secret=True)])], "dev")

    window.controller.open_request(request.id)
    window.controller.send()
    for _ in range(100):
        if window.session.active.response is not None:
            break
        _wait(50)
    response = window.session.active.response
    assert response is not None and response.status_code == 200
    assert json.loads(response.body) == {"path": "/users/42", "auth": "Bearer tok"}
    assert ws.history()[0].status == 200


def test_save_dialog_saves_into_new_folder(window):
    ws = window.workspace
    collection = ws.create_collection("Orders API", "https://api.example.com")
    window.request_panel.url_bar.url.setPlainText("{{baseUrl}}/orders?status=paid")

    def fill(dialog):
        dialog.name.setText("List orders")
        dialog._start_new()
        dialog.new_input.setText("Orders")
        dialog._commit_new()
        dialog._save()

    assert _with_dialog(window.controller.save, fill)
    tab = window.session.active
    location = ws.locate(tab.request.id)
    assert location.collection.id == collection.id and location.breadcrumb == ["Orders API", "Orders"]
    assert tab.saved and not tab.dirty


def test_response_can_take_almost_all_the_space(window):
    splitter = window.request_panel.splitter
    splitter.moveSplitter(0, 1)
    sizes = splitter.sizes()
    assert sizes[0] <= 40  # only the request's section tabs remain
    assert sizes[1] / sum(sizes) > 0.9
    splitter.toggle_maximized()  # double-click on the handle restores the split
    assert splitter.sizes()[0] > 100


def test_file_picked_in_the_editor_is_uploaded(window, server, tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("hello file")
    window.request_panel.url_bar.url.setPlainText(server + "/upload")
    window.request_panel._set_method("POST")
    window.request_panel.editor._mode_buttons["form"].setChecked(True)
    table = window.request_panel.editor.form_table
    ghost = table._rows[-1]
    ghost.key.setText("attachment")
    ghost.key.textEdited.emit("attachment")
    ghost.set_type("file", user=True)
    ghost.file_field.set_path(str(note))
    ghost.file_field.changed.emit()

    tab = window.session.active
    assert tab.request.form == [KeyValue("attachment", str(note), type="file")]
    window.controller.send()
    for _ in range(100):
        if tab.response is not None:
            break
        _wait(50)
    assert json.loads(tab.response.body) == {"type": "multipart/form-data", "has_file": True}


def test_ctrl_f_opens_search_in_the_response(window, server):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.controller.new_tab()
    apply_url(window.session.active.request, f"{server}/users/1")
    window.controller.send()
    for _ in range(100):
        if window.session.active.response is not None:
            break
        _wait(50)
    response = window.request_panel.response
    response.tabs.changed.emit("headers")  # searching jumps back to the body
    window.activateWindow()
    _wait(50)

    def press_find():
        QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        _wait(20)

    press_find()
    assert window.session.active.response_section == "body"
    assert response.find_bar.isVisible() and response.find_input.hasFocus()
    QTest.keyClicks(response.find_input, "users")
    assert response._find_count.text() == "1 match"
    press_find()  # again: stays open, text selected for retyping
    assert response.find_bar.isVisible() and response.find_input.selectedText() == "users"
