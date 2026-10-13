"""Serialize collections to the native Hitman format and to Postman v2.1."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from hitman.core.models import Auth, Collection, Folder, KeyValue, Node, Request, Variable

HITMAN_FORMAT_VERSION = "1.0"
POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

FORMATS = [
    # (id, label, description, file suffix)
    ("hitman", "Hitman collection", "JSON · keeps auth and variables", ".hitman.json"),
    ("postman", "Postman Collection v2.1", "JSON · opens in most API clients", ".postman_collection.json"),
]


def merged_variables(collection: Collection, extra: list[Variable] | None) -> list[dict]:
    """Collection variables plus optional extra (environment) ones; secrets are always dropped."""
    out: dict[str, str] = {}
    for var in collection.variables + (extra or []):
        if var.key and not var.secret:
            out[var.key] = var.value
    return [{"key": k, "value": v} for k, v in out.items()]


def to_json(data: dict, pretty: bool = True) -> str:
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------------- native

def _kv_list(rows: list[KeyValue]) -> list[dict]:
    out = []
    for row in rows:
        item = {"key": row.key, "value": row.value}
        if row.description:
            item["description"] = row.description
        if not row.enabled:
            item["enabled"] = False
        out.append(item)
    return out


def _auth_dict(auth: Auth) -> dict:
    if auth.type == "bearer":
        return {"type": "bearer", "token": auth.token}
    if auth.type == "basic":
        return {"type": "basic", "username": auth.username, "password": auth.password}
    if auth.type == "apikey":
        return {"type": "apikey", "key": auth.key, "value": auth.value, "in": auth.add_to}
    return {"type": auth.type}


def _hitman_request(req: Request) -> dict:
    item: dict = {"type": "request", "name": req.name, "method": req.method, "url": req.url}
    if req.params:
        item["params"] = _kv_list(req.params)
    if req.path_vars:
        item["pathVariables"] = _kv_list(req.path_vars)
    if req.headers:
        item["headers"] = _kv_list(req.headers)
    if req.auth.type != "inherit":
        item["auth"] = _auth_dict(req.auth)
    if req.body_mode == "raw":
        item["body"] = {"mode": "raw", "type": req.raw_type, "raw": req.body}
    elif req.body_mode in ("form", "urlencoded"):
        item["body"] = {"mode": req.body_mode, "fields": _kv_list(req.form)}
    return item


def _hitman_items(items: list[Node]) -> list[dict]:
    return [{"type": "folder", "name": n.name, "items": _hitman_items(n.items)} if isinstance(n, Folder)
            else _hitman_request(n) for n in items]


def export_hitman(collection: Collection, extra_variables: list[Variable] | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    data: dict = {
        "hitman": HITMAN_FORMAT_VERSION,
        "info": {"name": collection.name, "exportedAt": now},
        "auth": _auth_dict(collection.auth),
    }
    variables = merged_variables(collection, extra_variables)
    if variables:
        data["variables"] = variables
    data["items"] = _hitman_items(collection.items)
    return data


# ------------------------------------------------------------------ postman

def _pm_kv(rows: list[KeyValue]) -> list[dict]:
    out = []
    for row in rows:
        item = {"key": row.key, "value": row.value}
        if row.description:
            item["description"] = row.description
        if not row.enabled:
            item["disabled"] = True
        out.append(item)
    return out


def _pm_auth(auth: Auth) -> dict | None:
    if auth.type == "none":
        return {"type": "noauth"}
    if auth.type == "bearer":
        return {"type": "bearer", "bearer": [{"key": "token", "value": auth.token, "type": "string"}]}
    if auth.type == "basic":
        return {"type": "basic", "basic": [
            {"key": "username", "value": auth.username, "type": "string"},
            {"key": "password", "value": auth.password, "type": "string"}]}
    if auth.type == "apikey":
        return {"type": "apikey", "apikey": [
            {"key": "key", "value": auth.key, "type": "string"},
            {"key": "value", "value": auth.value, "type": "string"},
            {"key": "in", "value": auth.add_to, "type": "string"}]}
    return None  # inherit


def _pm_request(req: Request) -> dict:
    url: dict = {"raw": req.url}
    if req.params:
        url["query"] = _pm_kv(req.params)
    if req.path_vars:
        url["variable"] = _pm_kv(req.path_vars)
    request: dict = {"method": req.method, "header": _pm_kv(req.headers), "url": url}
    auth = _pm_auth(req.auth)
    if auth:
        request["auth"] = auth
    if req.body_mode == "raw":
        language = {"JSON": "json", "Text": "text", "JavaScript": "javascript", "HTML": "html", "XML": "xml"}
        request["body"] = {"mode": "raw", "raw": req.body,
                           "options": {"raw": {"language": language.get(req.raw_type, "text")}}}
    elif req.body_mode == "urlencoded":
        request["body"] = {"mode": "urlencoded", "urlencoded": _pm_kv(req.form)}
    elif req.body_mode == "form":
        request["body"] = {"mode": "formdata",
                           "formdata": [dict(row, type="text") for row in _pm_kv(req.form)]}
    return {"name": req.name, "request": request}


def _pm_items(items: list[Node]) -> list[dict]:
    return [{"name": n.name, "item": _pm_items(n.items)} if isinstance(n, Folder) else _pm_request(n)
            for n in items]


def export_postman(collection: Collection, extra_variables: list[Variable] | None = None) -> dict:
    data: dict = {"info": {"name": collection.name, "schema": POSTMAN_SCHEMA},
                  "item": _pm_items(collection.items)}
    auth = _pm_auth(collection.auth)
    if auth and auth["type"] != "noauth":
        data["auth"] = auth
    variables = merged_variables(collection, extra_variables)
    if variables:
        data["variable"] = variables
    return data


def export(collection: Collection, fmt: str, extra_variables: list[Variable] | None = None) -> dict:
    if fmt == "postman":
        return export_postman(collection, extra_variables)
    return export_hitman(collection, extra_variables)
