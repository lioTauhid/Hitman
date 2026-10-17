import ast

import pytest

from hitman.core.codegen import LANGUAGES, generate
from hitman.core.curl import CurlParseError, parse_curl
from hitman.core.http import resolve_request
from hitman.core.models import Auth, KeyValue, Request


def test_parse_curl_json_post():
    req = parse_curl("""curl -X POST 'https://api.example.com/v1/orders?dry=1' \\
      -H 'Content-Type: application/json' \\
      -H "Authorization: Bearer abc" \\
      --data-raw '{"sku": "TEE", "qty": 2}'""")
    assert req.method == "POST"
    assert req.url == "https://api.example.com/v1/orders?dry=1"
    assert [(p.key, p.value) for p in req.params] == [("dry", "1")]
    assert req.body_mode == "raw" and req.raw_type == "JSON"
    assert ("Authorization", "Bearer abc") in [(h.key, h.value) for h in req.headers]
    assert req.name == "/v1/orders"


def test_parse_curl_defaults_and_flags():
    req = parse_curl("curl -sSL https://x.dev/a -u bob:pw -d 'a=1&b=2'")
    assert req.method == "POST"
    assert req.auth == Auth(type="basic", username="bob", password="pw")
    assert req.body_mode == "urlencoded"
    assert [(f.key, f.value) for f in req.form] == [("a", "1"), ("b", "2")]


def test_parse_curl_form_and_get():
    assert parse_curl("curl -F name=x -F file=y https://x.dev/up").body_mode == "form"
    req = parse_curl("curl -G https://x.dev/search -d q=hi")
    assert req.method == "GET" and req.url == "https://x.dev/search?q=hi"


def test_parse_curl_ansi_c_quoting_and_equals_flags():
    req = parse_curl("curl --request=PUT --url=https://x.dev/a --data-raw $'{\"a\":\"it\\'s\"}'")
    assert req.method == "PUT" and req.body == '{"a":"it\'s"}'


def test_parse_curl_errors():
    with pytest.raises(CurlParseError):
        parse_curl("curl -X POST")


def _sample():
    req = Request(method="POST", url="https://x.dev/orders", headers=[KeyValue("Accept", "application/json")],
                  auth=Auth(type="bearer", token="tok"), body_mode="raw", body='{"ok": true, "n": null}')
    return resolve_request(req, {})


@pytest.mark.parametrize("lang", [lang for lang, _, _ in LANGUAGES])
def test_generate_every_language(lang):
    code = generate(lang, _sample())
    assert "https://x.dev/orders" in code
    assert "Bearer tok" in code


def test_generate_without_auth_and_valid_python():
    code = generate("python", _sample(), include_auth=False)
    assert "Bearer" not in code
    ast.parse(code)  # generated Python must be syntactically valid
    assert "True" in code and "None" in code


def test_generate_form_bodies():
    req = Request(method="POST", url="https://x.dev/f", body_mode="form", form=[KeyValue("a", "1")])
    resolved = resolve_request(req, {})
    assert "--form 'a=1'" in generate("curl", resolved)
    assert "multipart.NewWriter" in generate("go", resolved)
    ast.parse(generate("python", resolved))


def test_parse_curl_windows_cmd_format():
    command = ('curl ^"https://api.example.com/v1/orders?x=1^&y=2^" ^\n'
               '  -H ^"accept: application/json^" ^\n'
               '  --data-raw ^"^{^\\^"a^\\^":1^}^"')
    req = parse_curl(command)
    assert req.url == "https://api.example.com/v1/orders?x=1&y=2"
    assert ("accept", "application/json") in [(h.key, h.value) for h in req.headers]
    assert req.body == '{"a":1}' and req.method == "POST"


def test_parse_curl_powershell_continuations():
    req = parse_curl('curl.exe https://x.dev/a `\n  -H "A: b" `\n  -X DELETE')
    assert req.method == "DELETE" and req.headers[0].key == "A"
