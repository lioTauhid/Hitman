"""File fields in multipart/form-data bodies, across every layer."""

import ast
import json
import threading
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hitman.core.codegen import LANGUAGES, generate
from hitman.core.curl import parse_curl
from hitman.core.exporters import export_hitman, export_postman, to_json
from hitman.core.http import SendOptions, resolve_request, send
from hitman.core.importers import parse_import
from hitman.core.models import Collection, KeyValue, Request


def _upload_request(path: str) -> Request:
    return Request(method="POST", url="https://x.dev/upload", body_mode="form", form=[
        KeyValue("name", "Jo"),
        KeyValue("avatar", path, type="file"),
        KeyValue("empty", "", type="file"),          # no file picked: not sent
        KeyValue("off", "/x", type="file", enabled=False),
    ])


def test_key_value_type_roundtrip_and_legacy_rows():
    row = KeyValue("avatar", "/tmp/a.png", type="file")
    assert KeyValue.from_dict(row.to_dict()) == row
    assert KeyValue.from_dict({"key": "a", "value": "b"}).type == "text"  # data saved before file support
    req = _upload_request("/tmp/a.png")
    assert Request.from_dict(req.to_dict()) == req


def test_resolve_separates_files_and_skips_them_for_urlencoded():
    req = _upload_request("{{dir}}/a.png")
    resolved = resolve_request(req, {"dir": "/tmp"})
    assert resolved.form == [("name", "Jo")]
    assert resolved.files == [("avatar", "/tmp/a.png")]
    req.body_mode = "urlencoded"
    assert resolve_request(req, {}).files == []


class _Capture(BaseHTTPRequestHandler):
    received: dict = {}

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        message = BytesParser(policy=HTTP).parsebytes(
            f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body)
        _Capture.received = {part.get_param("name", header="content-disposition"): (
            part.get_filename(), part.get_content_type(), part.get_payload(decode=True)) for part in message.iter_parts()}
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_send_uploads_the_file(server, tmp_path):
    photo = tmp_path / "me.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\nimage-bytes")
    req = _upload_request(str(photo))
    req.url = server + "/upload"
    response = send(resolve_request(req, {}), SendOptions(use_system_proxy=False))
    assert response.ok and response.status_code == 200
    received = _Capture.received
    assert received["name"] == (None, "text/plain", b"Jo")
    assert received["avatar"] == ("me.png", "image/png", b"\x89PNG\r\n\x1a\nimage-bytes")
    assert set(received) == {"name", "avatar"}


def test_missing_file_is_reported_not_raised(tmp_path):
    req = _upload_request(str(tmp_path / "nope.pdf"))
    response = send(resolve_request(req, {}), SendOptions(use_system_proxy=False))
    assert not response.ok and "nope.pdf" in response.error


def test_curl_form_file_fields():
    req = parse_curl("curl https://x.dev/up -F 'avatar=@/tmp/a b.png;type=image/png' -F name=Jo --form-string 'h=@x'")
    assert [(f.key, f.value, f.type) for f in req.form] == [
        ("avatar", "/tmp/a b.png", "file"), ("name", "Jo", "text"), ("h", "@x", "text")]


@pytest.mark.parametrize("lang, expected", [
    ("curl", "--form 'avatar=@/tmp/me.png'"),
    ("python", '("avatar", open("/tmp/me.png", "rb"))'),
    ("fetch", 'form.append("avatar", await openAsBlob("/tmp/me.png"), "me.png");'),
    ("go", 'writer.CreateFormFile("avatar", "me.png")'),
    ("dart", "http.MultipartFile.fromPath('avatar', '/tmp/me.png')"),
])
def test_codegen_uploads_files(lang, expected):
    code = generate(lang, resolve_request(_upload_request("/tmp/me.png"), {}))
    assert expected in code
    assert "Jo" in code
    if lang == "python":
        ast.parse(code)


def test_codegen_covers_every_language():
    assert {lang for lang, _, _ in LANGUAGES} == {"curl", "python", "fetch", "go", "dart"}


@pytest.mark.parametrize("exporter", [export_hitman, export_postman])
def test_import_export_keeps_file_fields(exporter):
    collection = Collection(name="Uploads", items=[_upload_request("/tmp/me.png")])
    imported = parse_import(to_json(exporter(collection))).collection.items[0]
    assert [(f.key, f.value, f.type, f.enabled) for f in imported.form] == [
        ("name", "Jo", "text", True), ("avatar", "/tmp/me.png", "file", True),
        ("empty", "", "file", True), ("off", "/x", "file", False)]


def test_postman_file_entry_with_src_list():
    data = {"info": {"name": "P", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/"},
            "item": [{"name": "Up", "request": {"method": "POST", "url": "https://x", "body": {
                "mode": "formdata", "formdata": [{"key": "doc", "type": "file", "src": ["/a.pdf", "/b.pdf"]}]}}}]}
    row = parse_import(json.dumps(data)).collection.items[0].form[0]
    assert (row.key, row.value, row.type) == ("doc", "/a.pdf", "file")


def test_openapi_binary_fields_become_file_fields():
    spec = {"openapi": "3.0.0", "info": {"title": "T"}, "paths": {"/up": {"post": {"requestBody": {"content": {
        "multipart/form-data": {"schema": {"type": "object", "properties": {
            "file": {"type": "string", "format": "binary"}, "title": {"type": "string", "example": "Hi"}}}}}}}}}}
    req = parse_import(json.dumps(spec)).collection.items[0]
    assert req.body_mode == "form"
    assert [(f.key, f.value, f.type) for f in req.form] == [("file", "", "file"), ("title", "Hi", "text")]
