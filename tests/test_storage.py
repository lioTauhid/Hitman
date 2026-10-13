import pytest

from hitman.core.models import Auth, Collection, Environment, Folder, HistoryEntry, Request, Variable
from hitman.storage.database import Database
from hitman.storage.repositories import (CollectionRepository, EnvironmentRepository, HistoryRepository,
                                         SettingsRepository)


@pytest.fixture()
def db():
    database = Database(":memory:")
    yield database
    database.close()


def test_collection_tree_roundtrip(db):
    repo = CollectionRepository(db)
    req = Request(name="Get user", url="https://x.dev/u")
    col = Collection(name="API", auth=Auth(type="bearer", token="t"), variables=[Variable("baseUrl", "b")],
                     items=[Folder(name="Users", items=[req]), Request(name="Health")])
    repo.create(col)
    loaded = repo.load_all()
    assert len(loaded) == 1
    assert loaded[0].auth.token == "t" and loaded[0].variables[0].key == "baseUrl"
    users, health = loaded[0].items
    assert users.name == "Users" and users.items[0].url == "https://x.dev/u"
    assert health.name == "Health"


def test_add_after_rename_update_delete(db):
    repo = CollectionRepository(db)
    first, second = Request(name="A"), Request(name="B")
    col = Collection(name="API", items=[first, second])
    repo.create(col)
    repo.add_item(col.id, None, Request(name="A copy"), after_id=first.id)
    assert [n.name for n in repo.load_all()[0].items] == ["A", "A copy", "B"]

    repo.rename_item(second.id, "B2")
    second.method = "POST"
    second.name = "B2"
    repo.update_request(second)
    names = [(n.name, n.method) for n in repo.load_all()[0].items]
    assert ("B2", "POST") in names

    folder = Folder(name="F", items=[Request(name="inner")])
    repo.add_item(col.id, None, folder)
    repo.delete_item(folder.id)  # cascades to children
    assert len(repo.load_all()[0].items) == 3
    repo.delete(col.id)
    assert repo.load_all() == []


def test_environments_history_settings(db):
    envs = EnvironmentRepository(db)
    envs.replace_all([Environment(id="g", name="Globals", is_global=True),
                      Environment(id="dev", name="Dev", variables=[Variable("k", "v", secret=True)])])
    loaded = envs.load_all()
    assert loaded[0].is_global and loaded[1].variables[0].secret

    history = HistoryRepository(db)
    history.add(HistoryEntry(method="GET", url="https://x", status=200, duration_ms=5, size=10,
                             created_at=1.0, request=Request(name="x")))
    entries = history.list()
    assert entries[0].status == 200 and entries[0].request.name == "x"
    history.clear()
    assert history.list() == []

    settings = SettingsRepository(db)
    assert settings.get("missing", 3) == 3
    settings.set("theme", {"mode": "light"})
    assert settings.get("theme") == {"mode": "light"}
