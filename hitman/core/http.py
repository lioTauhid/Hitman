"""Turn a Request into a concrete HTTP call and execute it with `requests`."""

from __future__ import annotations

import base64
import mimetypes
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

import requests

from hitman import APP_NAME, __version__
from hitman.core.models import Auth, Request
from hitman.core.urls import ensure_scheme, split_url, substitute_path_vars
from hitman.core.variables import resolve

USER_AGENT = f"{APP_NAME}/{__version__}"

RAW_CONTENT_TYPES = {
    "JSON": "application/json",
    "Text": "text/plain",
    "JavaScript": "application/javascript",
    "HTML": "text/html",
    "XML": "application/xml",
}


class RequestCancelled(Exception):
    pass


@dataclass
class SendOptions:
    timeout_ms: int = 30000
    follow_redirects: bool = True
    max_redirects: int = 10
    verify_ssl: bool = True
    encode_url: bool = True
    use_system_proxy: bool = True


@dataclass
class ResolvedRequest:
    """A request with every variable substituted, ready to send or turn into code."""
    method: str
    url: str
    headers: list[tuple[str, str]] = field(default_factory=list)
    auth_headers: set[str] = field(default_factory=set)  # lower-cased header names added by auth
    body_kind: str = "none"  # none | raw | urlencoded | form
    body: str = ""
    form: list[tuple[str, str]] = field(default_factory=list)   # text fields
    files: list[tuple[str, str]] = field(default_factory=list)  # (field name, file path), form-data only
    raw_type: str = "JSON"

    def header(self, name: str) -> str | None:
        lname = name.lower()
        for k, v in self.headers:
            if k.lower() == lname:
                return v
        return None


@dataclass
class HttpResponse:
    status_code: int = 0
    reason: str = ""
    elapsed_ms: int = 0
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""
    encoding: str | None = None
    url: str = ""
    method: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def header_bytes(self) -> int:
        status_line = len(f"HTTP/1.1 {self.status_code} {self.reason}\r\n")
        return status_line + sum(len(k) + len(v) + 4 for k, v in self.headers) + 2

    @property
    def size(self) -> int:
        return len(self.body) + self.header_bytes

    @property
    def content_type(self) -> str:
        for k, v in self.headers:
            if k.lower() == "content-type":
                return v.lower()
        return ""

    def text(self) -> str:
        encoding = self.encoding or "utf-8"
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ resolving

def effective_auth(request: Request, collection_auth: Auth | None) -> Auth:
    if request.auth.type == "inherit":
        return collection_auth if collection_auth and collection_auth.type != "inherit" else Auth(type="none")
    return request.auth


def _auth_parts(auth: Auth, scope: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (headers, query params) produced by an auth config."""
    if auth.type == "bearer":
        return [("Authorization", f"Bearer {resolve(auth.token, scope)}")], []
    if auth.type == "basic":
        raw = f"{resolve(auth.username, scope)}:{resolve(auth.password, scope)}"
        return [("Authorization", "Basic " + base64.b64encode(raw.encode()).decode())], []
    if auth.type == "apikey" and auth.key:
        pair = (resolve(auth.key, scope), resolve(auth.value, scope))
        return ([pair], []) if auth.add_to == "header" else ([], [pair])
    return [], []


def resolve_request(request: Request, scope: dict, collection_auth: Auth | None = None) -> ResolvedRequest:
    path, query = split_url(request.url)
    path = substitute_path_vars(path, request.path_vars)
    url = resolve(path + (f"?{query}" if query else ""), scope)

    auth_headers, auth_query = _auth_parts(effective_auth(request, collection_auth), scope)
    if auth_query:
        extra = "&".join(f"{k}={v}" for k, v in auth_query)
        url += ("&" if "?" in url else "?") + extra

    headers = [(resolve(h.key, scope), resolve(h.value, scope))
               for h in request.headers if h.enabled and h.key]
    present = {k.lower() for k, _ in headers}
    added_auth = set()
    for k, v in auth_headers:
        if k.lower() not in present:
            headers.append((k, v))
            added_auth.add(k.lower())

    resolved = ResolvedRequest(method=request.method, url=ensure_scheme(url), headers=headers,
                               auth_headers=added_auth, raw_type=request.raw_type)

    if request.body_mode == "raw" and request.body:
        resolved.body_kind = "raw"
        resolved.body = resolve(request.body, scope)
        if "content-type" not in present:
            resolved.headers.append(("Content-Type", RAW_CONTENT_TYPES.get(request.raw_type, "text/plain")))
    elif request.body_mode in ("urlencoded", "form"):
        rows = [f for f in request.form if f.enabled and f.key]
        resolved.body_kind = request.body_mode
        resolved.form = [(resolve(f.key, scope), resolve(f.value, scope)) for f in rows if not f.is_file]
        if request.body_mode == "form":  # url-encoded bodies can't carry files
            resolved.files = [(resolve(f.key, scope), resolve(f.value, scope)) for f in rows if f.is_file and f.value]
    return resolved


def auto_headers(request: Request, resolved: ResolvedRequest) -> list[tuple[str, str, str]]:
    """Headers added automatically when sending, as (key, value, note) for display."""
    user = {h.key.lower() for h in request.headers if h.enabled and h.key}
    try:
        host = requests.utils.urlparse(resolved.url).netloc or "—"
    except ValueError:
        host = "—"
    rows = [("Host", host, "Calculated when sent")]
    defaults = [("User-Agent", USER_AGENT), ("Accept", "*/*"),
                ("Accept-Encoding", "gzip, deflate"), ("Connection", "keep-alive")]
    rows += [(k, v, "") for k, v in defaults if k.lower() not in user]
    if resolved.body_kind != "none":
        rows.append(("Content-Length", "Calculated when sent", ""))
        if resolved.body_kind == "raw" and "content-type" not in user:
            rows.append(("Content-Type", RAW_CONTENT_TYPES.get(request.raw_type, "text/plain"), "From the body type"))
        elif resolved.body_kind == "urlencoded" and "content-type" not in user:
            rows.append(("Content-Type", "application/x-www-form-urlencoded", "From the body type"))
        elif resolved.body_kind == "form" and "content-type" not in user:
            rows.append(("Content-Type", "multipart/form-data; boundary=…", "From the body type"))
    for k, v in resolved.headers:
        if k.lower() in resolved.auth_headers:
            masked = v.split(" ", 1)[0] + " ••••••••" if " " in v else "••••••••"
            rows.append((k, masked, "From the Authorization tab"))
    return rows


# -------------------------------------------------------------------- sending

def send(resolved: ResolvedRequest, options: SendOptions,
         cancel: threading.Event | None = None) -> HttpResponse:
    """Execute the request. Never raises for network problems; sets `error` instead."""
    cancel = cancel or threading.Event()
    session = requests.Session()
    session.trust_env = options.use_system_proxy
    session.max_redirects = max(0, options.max_redirects)

    headers = requests.structures.CaseInsensitiveDict({"User-Agent": USER_AGENT})
    for k, v in resolved.headers:
        headers[k] = v

    open_files = ExitStack()
    data = files = None
    if resolved.body_kind == "raw":
        data = resolved.body.encode("utf-8")
    elif resolved.body_kind == "urlencoded":
        data = resolved.form
    elif resolved.body_kind == "form":
        try:
            files = _multipart_parts(resolved, open_files) or None
        except OSError as exc:
            open_files.close()
            session.close()
            return _error(resolved, time.perf_counter(),
                          f"Can't read the file {exc.filename or ''}: {exc.strerror or exc}.")
        if files is None:
            data = b""

    timeout = options.timeout_ms / 1000 if options.timeout_ms > 0 else None
    started = time.perf_counter()
    try:
        prepared = session.prepare_request(
            requests.Request(resolved.method, resolved.url, headers=headers, data=data, files=files))
        if not options.encode_url:
            prepared.url = resolved.url
        raw = session.send(prepared, stream=True, timeout=timeout,
                           verify=options.verify_ssl, allow_redirects=options.follow_redirects)
        chunks = []
        try:
            for chunk in raw.iter_content(64 * 1024):
                if cancel.is_set():
                    raise RequestCancelled
                chunks.append(chunk)
        finally:
            raw.close()
        elapsed = int((time.perf_counter() - started) * 1000)
        return HttpResponse(
            status_code=raw.status_code,
            reason=raw.reason or "",
            elapsed_ms=elapsed,
            headers=list(raw.raw.headers.items()) if raw.raw is not None else list(raw.headers.items()),
            body=b"".join(chunks),
            encoding=raw.encoding or _sniff_encoding(raw),
            url=raw.url,
            method=resolved.method,
        )
    except RequestCancelled:
        raise
    except requests.exceptions.SSLError as exc:
        return _error(resolved, started, f"SSL error: {_short(exc)}. Turn off certificate verification in Settings for self-signed servers.")
    except requests.exceptions.ConnectTimeout:
        return _error(resolved, started, "Connection timed out.")
    except requests.exceptions.ReadTimeout:
        return _error(resolved, started, "The server took too long to respond.")
    except requests.exceptions.TooManyRedirects:
        return _error(resolved, started, f"Stopped after {options.max_redirects} redirects.")
    except requests.exceptions.ConnectionError as exc:
        return _error(resolved, started, f"Could not connect: {_short(exc)}")
    except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema) as exc:
        return _error(resolved, started, f"Invalid URL: {_short(exc)}")
    except requests.exceptions.RequestException as exc:
        return _error(resolved, started, _short(exc))
    except (ValueError, UnicodeError) as exc:
        return _error(resolved, started, f"Invalid request: {exc}")
    finally:
        open_files.close()
        session.close()


def _multipart_parts(resolved: ResolvedRequest, open_files: ExitStack) -> list:
    """Text fields and opened files in the shape `requests` expects for multipart bodies."""
    parts: list = [(key, (None, value)) for key, value in resolved.form]
    for key, path in resolved.files:
        file_path = Path(path).expanduser()
        handle = open_files.enter_context(open(file_path, "rb"))
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        parts.append((key, (file_path.name, handle, content_type)))
    return parts


def _sniff_encoding(raw: requests.Response) -> str | None:
    ctype = raw.headers.get("Content-Type", "").lower()
    if "json" in ctype or "javascript" in ctype or ctype.startswith("text/"):
        return "utf-8"
    return None


def _short(exc: Exception) -> str:
    text = str(exc)
    # requests wraps urllib3 errors with long reprs; keep the meaningful tail.
    if "Caused by" in text:
        text = text.split("Caused by", 1)[1].strip(" ()'\"")
    return text[:240]


def _error(resolved: ResolvedRequest, started: float, message: str) -> HttpResponse:
    return HttpResponse(elapsed_ms=int((time.perf_counter() - started) * 1000),
                        url=resolved.url, method=resolved.method, error=message)
