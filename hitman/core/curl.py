"""Parse a cURL command line into a Request."""

from __future__ import annotations

import codecs
import json
import re
import shlex

from hitman.core.models import METHODS, Auth, KeyValue, Request
from hitman.core.urls import apply_url, split_url


class CurlParseError(ValueError):
    pass


# Flags that take a value we ignore, and flags without a value we ignore.
_IGNORED_WITH_VALUE = {"-o", "--output", "-m", "--max-time", "--connect-timeout", "-w",
                       "--write-out", "--retry", "-x", "--proxy", "--cacert", "--cert", "--key"}
_IGNORED_FLAGS = {"-L", "--location", "-k", "--insecure", "-s", "--silent", "-S", "--show-error",
                  "-v", "--verbose", "-i", "--include", "--compressed", "-f", "--fail", "-N",
                  "--no-buffer", "--http1.0", "--http1.1", "--http2", "--http2-prior-knowledge", "-#",
                  "--progress-bar", "-g", "--globoff"}
_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii"}
_SHORT_NO_VALUE = set("LksSvifNg#GI")


def looks_like_curl(text: str) -> bool:
    return bool(re.match(r"^\s*curl(\.exe)?\s", text or ""))


def _ansi_c_quotes(text: str) -> str:
    """Convert bash $'...' strings (used by browsers' "Copy as cURL") to plain quoted strings."""
    def repl(match: re.Match) -> str:
        decoded = codecs.decode(match.group(1).encode("latin-1", "backslashreplace"), "unicode_escape")
        return shlex.quote(decoded)
    return re.sub(r"\$'((?:[^'\\]|\\.)*)'", repl, text)


def _tokenize(command: str) -> list[str]:
    text = command.strip()
    text = re.sub(r"\\\r?\n", " ", text)   # bash line continuations
    text = re.sub(r"\^\r?\n", " ", text)   # cmd.exe line continuations
    text = _ansi_c_quotes(text)
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise CurlParseError(f"Could not read the command: {exc}") from exc


def _expand_flags(tokens: list[str]) -> list[str]:
    """Split combined flags (-sSL), attached values (-XPOST) and --flag=value forms."""
    out: list[str] = []
    for tok in tokens:
        if tok.startswith("--") and "=" in tok:
            flag, val = tok.split("=", 1)
            out.extend([flag, val])
            continue
        if tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
            if all(ch in _SHORT_NO_VALUE for ch in tok[1:]):
                out.extend(f"-{ch}" for ch in tok[1:])
                continue
            if tok[1] in "XHdFuAbe":
                out.extend([tok[:2], tok[2:]])
                continue
        out.append(tok)
    return out


def parse_curl(command: str) -> Request:
    tokens = _tokenize(command)
    if not tokens or tokens[0] not in ("curl", "curl.exe"):
        raise CurlParseError("The text doesn't start with 'curl'.")
    tokens = _expand_flags(tokens[1:])

    method: str | None = None
    url = ""
    headers: list[KeyValue] = []
    data: list[str] = []
    urlencoded: list[KeyValue] = []
    form: list[KeyValue] = []
    auth = Auth(type="none")
    force_get = False

    pos = 0
    while pos < len(tokens):
        tok = tokens[pos]
        pos += 1

        def value() -> str:
            nonlocal pos
            if pos >= len(tokens):
                raise CurlParseError(f"Missing value after {tok}.")
            pos += 1
            return tokens[pos - 1]

        if tok in ("-X", "--request"):
            method = value().upper()
        elif tok in ("-H", "--header"):
            raw = value()
            key, _, val = raw.partition(":")
            if key.strip():
                headers.append(KeyValue(key=key.strip(), value=val.strip()))
        elif tok in _DATA_FLAGS:
            data.append(value())
        elif tok == "--data-urlencode":
            key, sep, val = value().partition("=")
            urlencoded.append(KeyValue(key=key, value=val) if sep else KeyValue(key="", value=key))
        elif tok in ("-F", "--form"):
            key, _, val = value().partition("=")
            form.append(KeyValue(key=key, value=val))
        elif tok in ("-u", "--user"):
            user, _, password = value().partition(":")
            auth = Auth(type="basic", username=user, password=password)
        elif tok in ("-A", "--user-agent"):
            headers.append(KeyValue(key="User-Agent", value=value()))
        elif tok in ("-b", "--cookie"):
            headers.append(KeyValue(key="Cookie", value=value()))
        elif tok in ("-e", "--referer"):
            headers.append(KeyValue(key="Referer", value=value()))
        elif tok in ("-G", "--get"):
            force_get = True
        elif tok in ("-I", "--head"):
            method = "HEAD"
        elif tok == "--url":
            url = value()
        elif tok in _IGNORED_WITH_VALUE:
            value()
        elif tok in _IGNORED_FLAGS or tok.startswith("-"):
            continue
        elif not url:
            url = tok

    if not url:
        raise CurlParseError("No URL found in the cURL command.")

    request = Request(auth=auth, headers=headers)
    content_type = next((h.value.lower() for h in headers if h.key.lower() == "content-type"), "")

    if force_get and (data or urlencoded):
        pairs = "&".join(data + [f"{p.key}={p.value}" for p in urlencoded])
        url += ("&" if "?" in url else "?") + pairs
        data, urlencoded = [], []

    if form:
        request.body_mode, request.form = "form", form
    elif urlencoded:
        request.body_mode, request.form = "urlencoded", urlencoded + _pairs("&".join(data))
    elif data:
        body = "&".join(data)
        _assign_data_body(request, body, content_type)

    has_body = request.body_mode != "none"
    request.method = method if method in METHODS else ("POST" if has_body else "GET")
    apply_url(request, url)
    path = split_url(url)[0]
    request.name = re.sub(r"^[a-z]+://[^/]+", "", path) or path or "Imported request"
    return request


def _pairs(text: str) -> list[KeyValue]:
    out = []
    for part in text.split("&"):
        if part:
            key, _, val = part.partition("=")
            out.append(KeyValue(key=key, value=val))
    return out


def _assign_data_body(request: Request, body: str, content_type: str) -> None:
    looks_json = body.lstrip()[:1] in ("{", "[")
    if "json" in content_type or (not content_type and looks_json and _is_json(body)):
        request.body_mode, request.raw_type, request.body = "raw", "JSON", body
    elif "xml" in content_type:
        request.body_mode, request.raw_type, request.body = "raw", "XML", body
    elif "x-www-form-urlencoded" in content_type or (
            not content_type and re.fullmatch(r"[^=&\s]+=[^&]*(&[^=&\s]+=[^&]*)*", body)):
        request.body_mode, request.form = "urlencoded", _pairs(body)
    else:
        request.body_mode, request.raw_type, request.body = "raw", "Text", body


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except ValueError:
        return False
