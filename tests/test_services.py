import pytest

from hitman.core.http import HttpResponse
from hitman.core.models import Auth, Request, Variable
from hitman.services.session import Session
from hitman.services.workspace import Workspace
from hitman.storage.database import Database


@pytest.fixture()
def workspace():
    ws = Workspace(Database(":memory:"))
    yield ws
    ws.db.close()


def test_workspace_seeds_globals_and_scopes(workspace):
    assert workspace.global_environment is not None
    col = workspace.create_collection("API", "https://api.dev", auth_type="bearer")
    assert col.auth.token == "{{accessToken}}"
    env = workspace.global_environment.copy()
    env.variables = [Variable("baseUrl", "https://global"), Variable("token", "g")]
    from hitman.core.models import Environment
    dev = Environment(id="dev", name="Dev", variables=[Variable("token", "d")])
    workspace.save_environments([env, dev], "dev")
    scope = workspace.variable_scope(workspace.collection(col.id))
    assert scope == {"baseUrl": "https://global", "token": "d"}


def test_workspace_request_lifecycle(workspace):
    col = workspace.create_collection("API")
    folder = workspace.add_folder(col.id, None, "Users")
    req = Request(name="Get user", url="https://x/users/1")
    workspace.add_request(col.id, folder.id, req)
    loc = workspace.locate(req.id)
    assert loc.breadcrumb == ["API", "Users"] and loc.parent_id == folder.id
    workspace.rename(req.id, "Fetch user")
    assert workspace.saved_request(req.id).name == "Fetch user"
    copy = workspace.duplicate_collection(col.id)
    assert copy.name == "API copy" and workspace.locate(req.id).collection.id == col.id
    workspace.delete_item(folder.id)
    assert workspace.saved_request(req.id) is None


def test_history_records_errors_without_status(workspace):
    req = Request(name="x", method="POST", url="https://x")
    workspace.record_history(req, HttpResponse(url="https://x", method="POST", error="boom"), None)
    entry = workspace.history()[0]
    assert entry.status is None and entry.method == "POST"


def test_session_dirty_reuse_and_sync():
    session = Session()
    blank = session.active
    saved = Request(name="Saved", url="https://x")
    tab = session.open_saved(saved)
    assert len(session.tabs) == 1 and session.active is tab and blank not in session.tabs  # pristine tab reused
    assert not tab.dirty
    tab.request.url = "https://y"
    assert tab.dirty
    session.revert(tab.id)
    assert not tab.dirty and tab.request.url == "https://x"

    session.new_tab()
    assert len(session.tabs) == 2  # "+" always adds a tab

    renamed = saved.copy()
    renamed.name = "Renamed"
    session.sync_saved(lambda rid: renamed if rid == saved.id else None)
    assert tab.request.name == "Renamed" and not tab.dirty
    session.sync_saved(lambda rid: None)  # deleted from the collection
    assert all(t.request.id != saved.id for t in session.tabs)


def test_session_state_roundtrip():
    session = Session()
    req = Request(name="Saved", url="https://x", auth=Auth(type="none"))
    tab = session.open_saved(req)
    tab.request.url = "https://changed"
    state = session.to_state()

    restored = Session()
    restored.restore(state, lambda rid: req.copy() if rid == req.id else None)
    assert restored.active.request.url == "https://changed"
    assert restored.active.dirty and restored.active.saved
