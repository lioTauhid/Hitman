"""URL helpers that keep a request's URL, query params and path variables in sync.

Query strings are handled as raw text (no percent-decoding) so that
{{variables}} and the user's exact spelling survive round trips.
"""

from __future__ import annotations

import re

from hitman.core.models import KeyValue, Request

PATH_VAR_RE = re.compile(r"/:([A-Za-z_]\w*)")


def split_url(url: str) -> tuple[str, str]:
    """Split into (path part, query string) at the first '?'."""
    base, sep, query = url.partition("?")
    return base, query if sep else ""


def parse_query(query: str) -> list[tuple[str, str]]:
    pairs = []
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        pairs.append((key, value))
    return pairs


def build_query(params: list[KeyValue]) -> str:
    parts = []
    for p in params:
        if not p.enabled or not p.key:
            continue
        parts.append(f"{p.key}={p.value}" if p.value != "" else p.key)
    return "&".join(parts)


def path_keys(path: str) -> list[str]:
    seen: list[str] = []
    for key in PATH_VAR_RE.findall(path):
        if key not in seen:
            seen.append(key)
    return seen


def apply_url(request: Request, url: str) -> None:
    """The user edited the URL: re-derive params and path variables from it."""
    request.url = url
    path, query = split_url(url)
    descriptions = {p.key: p.description for p in request.params}
    parsed = [KeyValue(key=k, value=v, description=descriptions.get(k, ""))
              for k, v in parse_query(query)]
    disabled = [p for p in request.params if not p.enabled]
    request.params = parsed + disabled
    sync_path_vars(request, path)


def apply_params(request: Request) -> None:
    """The user edited the params table: rebuild the URL's query string."""
    path, _ = split_url(request.url)
    query = build_query(request.params)
    request.url = f"{path}?{query}" if query else path


def sync_path_vars(request: Request, path: str | None = None) -> None:
    if path is None:
        path = split_url(request.url)[0]
    existing = {p.key: p for p in request.path_vars}
    request.path_vars = [existing.get(k) or KeyValue(key=k) for k in path_keys(path)]


def substitute_path_vars(path: str, path_vars: list[KeyValue]) -> str:
    values = {p.key: p.value for p in path_vars if p.value}

    def repl(match: re.Match) -> str:
        key = match.group(1)
        return "/" + values[key] if key in values else match.group(0)

    return PATH_VAR_RE.sub(repl, path)


def ensure_scheme(url: str) -> str:
    stripped = url.strip()
    if stripped and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", stripped):
        return "http://" + stripped
    return stripped
