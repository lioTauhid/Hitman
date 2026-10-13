import base64
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hitman.core.http import SendOptions, auto_headers, resolve_request, send
from hitman.core.models import Auth, KeyValue, Request


def test_bearer_from_collection_when_inheriting():
    req = Request(url="{{baseUrl}}/me", auth=Auth(type="inherit"))
    resolved = resolve_request(req, {"baseUrl": "https://api.dev", "accessToken": "t0k"},
                               Auth.with_variables("bearer"))
    assert resolved.url == "https://api.dev/me"
    assert resolved.header("Authorization") == "Bearer t0k"
    assert resolved.auth_headers == {"authorization"}


def test_basic_auth_and_user_header_precedence():
    req = Request(url="https://x.dev", auth=Auth(type="basic", username="u", password="p"))
    resolved = resolve_request(req, {})
    assert resolved.header("Authorization") == "Basic " + base64.b64encode(b"u:p").decode()
    req.headers = [KeyValue("Authorization", "Custom 1")]
    assert resolve_request(req, {}).header("Authorization") == "Custom 1"


def test_api_key_in_query():
    req = Request(url="https://x.dev/a?x=1", auth=Auth(type="apikey", key="api_key", value="{{k}}", add_to="query"))
    assert resolve_request(req, {"k": "secret"}).url == "https://x.dev/a?x=1&api_key=secret"


def test_raw_json_body_gets_content_type():
    req = Request(method="POST", url="https://x.dev", body_mode="raw", raw_type="JSON", body='{"id": "{{id}}"}')
    resolved = resolve_request(req, {"id": "7"})
    assert resolved.body == '{"id": "7"}'
    assert resolved.header("Content-Type") == "application/json"
    keys = [k for k, _, _ in auto_headers(req, resolved)]
    assert "Content-Type" in keys and "Content-Length" in keys


def test_path_variables_substituted():
    req = Request(url="https://x.dev/users/:id", path_vars=[KeyValue("id", "{{uid}}")])
    assert resolve_request(req, {"uid": "42"}).url == "https://x.dev/users/42"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        payload = b'{"echo": ' + body + b', "ct": "' + self.headers.get("Content-Type", "").encode() + b'"}'
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_send_roundtrip(server):
    req = Request(method="POST", url=server + "/echo", body_mode="raw", raw_type="JSON", body='{"a": 1}')
    response = send(resolve_request(req, {}), SendOptions(use_system_proxy=False))
    assert response.ok and response.status_code == 201
    assert b'"echo": {"a": 1}' in response.body
    assert b'"ct": "application/json"' in response.body
    assert [v for k, v in response.headers if k.lower() == "set-cookie"] == ["a=1", "b=2"]
    assert response.size > len(response.body)


def test_send_connection_error_is_reported():
    req = Request(url="http://127.0.0.1:1/nothing")
    response = send(resolve_request(req, {}), SendOptions(timeout_ms=2000, use_system_proxy=False))
    assert not response.ok and response.error
