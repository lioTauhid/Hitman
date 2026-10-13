from hitman.core.models import KeyValue, Request, Variable
from hitman.core.urls import apply_params, apply_url, ensure_scheme, path_keys, substitute_path_vars
from hitman.core.variables import build_scope, is_known, resolve


def test_apply_url_parses_params_and_path_vars():
    req = Request()
    apply_url(req, "{{baseUrl}}/users/:id?include=orders&page=2")
    assert [(p.key, p.value) for p in req.params] == [("include", "orders"), ("page", "2")]
    assert [p.key for p in req.path_vars] == ["id"]


def test_apply_url_keeps_disabled_params_and_descriptions():
    req = Request(params=[KeyValue("include", "orders", "Embed", True), KeyValue("fields", "id", "Sparse", False)])
    apply_url(req, "https://x.dev/users?include=all")
    assert req.params[0] == KeyValue("include", "all", "Embed", True)
    assert req.params[1] == KeyValue("fields", "id", "Sparse", False)


def test_apply_params_rebuilds_query():
    req = Request(url="https://x.dev/a?old=1")
    req.params = [KeyValue("page", "1"), KeyValue("flag", ""), KeyValue("off", "x", enabled=False)]
    apply_params(req)
    assert req.url == "https://x.dev/a?page=1&flag"


def test_path_vars_survive_url_edits():
    req = Request()
    apply_url(req, "https://x.dev/users/:id")
    req.path_vars[0].value = "42"
    apply_url(req, "https://x.dev/users/:id/orders")
    assert req.path_vars[0].value == "42"
    assert substitute_path_vars("https://x.dev/users/:id/orders", req.path_vars) == "https://x.dev/users/42/orders"


def test_path_keys_ignore_ports():
    assert path_keys("http://localhost:8080/items/:itemId") == ["itemId"]


def test_resolve_known_unknown_and_dynamic():
    scope = build_scope([Variable("baseUrl", "https://api.dev")], [Variable("token", "abc"), Variable("off", "x", enabled=False)])
    assert resolve("{{baseUrl}}/a?t={{ token }}", scope) == "https://api.dev/a?t=abc"
    assert resolve("{{missing}}", scope) == "{{missing}}"
    assert resolve("{{off}}", scope) == "{{off}}"
    assert len(resolve("{{$guid}}", scope)) == 36
    assert is_known("$timestamp", scope) and not is_known("missing", scope)


def test_later_scope_layers_win():
    scope = build_scope([Variable("baseUrl", "collection")], [Variable("baseUrl", "env")])
    assert scope["baseUrl"] == "env"


def test_ensure_scheme():
    assert ensure_scheme("example.com/a") == "http://example.com/a"
    assert ensure_scheme("https://example.com") == "https://example.com"
