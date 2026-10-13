"""Widget-level checks, run offscreen."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hitman.core.models import KeyValue, Request  # noqa: E402
from hitman.services.session import OpenTab  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from hitman.ui.fonts import load_fonts
    from hitman.ui.theme import ThemeManager

    application = QApplication.instance() or QApplication([])
    load_fonts()
    ThemeManager(application).configure("dark", 13)
    return application


def test_key_value_editor_ghost_row(app):
    from hitman.ui.widgets.key_value import KeyValueEditor

    editor = KeyValueEditor()
    changes = []
    editor.changed.connect(lambda: changes.append(editor.rows()))
    editor.set_rows([KeyValue("a", "1")])
    assert editor.rows() == [KeyValue("a", "1")] and not changes
    ghost = editor._rows[-1]
    ghost.key.setText("b")
    ghost.key.textEdited.emit("b")
    assert [r.key for r in editor.rows()] == ["a", "b"]
    assert editor._rows[-1].ghost  # a fresh ghost row was appended

    editor.set_bulk(True)
    editor.bulk.setPlainText("x: 1\n//y: 2")
    editor.set_bulk(False)
    assert editor.rows() == [KeyValue("x", "1"), KeyValue("y", "2", enabled=False)]


def test_request_panel_syncs_url_and_params(app):
    from hitman.core.http import resolve_request
    from hitman.ui.request.request_panel import RequestPanel

    panel = RequestPanel(lambda: {"base": "https://api.dev"}, lambda tab: resolve_request(tab.request, {}))
    request = Request()
    tab = OpenTab(request=request, baseline=request.copy())
    panel.bind(tab, [], "")
    panel.url_bar.url.setPlainText("{{base}}/users/:id?page=2")
    assert [(p.key, p.value) for p in request.params] == [("page", "2")]
    assert [p.key for p in request.path_vars] == ["id"]
    assert panel.editor.params_table.rows()[0].key == "page"

    rows = panel.editor.params_table.rows() + [KeyValue("limit", "10")]
    panel.editor.params_table.set_rows(rows)
    panel.editor._edit("params")
    assert request.url == "{{base}}/users/:id?page=2&limit=10"
    assert panel.url_bar.url.toPlainText() == request.url
    assert tab.dirty


def test_curl_paste_is_detected(app):
    from PySide6.QtCore import QMimeData

    from hitman.ui.request.url_bar import UrlEdit

    edit = UrlEdit(lambda: {})
    pasted = []
    edit.curl_pasted.connect(pasted.append)
    mime = QMimeData()
    mime.setText("curl https://x.dev -H 'A: b'")
    edit.insertFromMimeData(mime)
    assert pasted and edit.toPlainText() == ""
    mime.setText("https://x.dev/a\n")
    edit.insertFromMimeData(mime)
    assert edit.toPlainText() == "https://x.dev/a"
