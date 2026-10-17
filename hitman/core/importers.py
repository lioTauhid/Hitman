"""Detect and import collection files: Hitman JSON, Postman v2.x, OpenAPI 3 and cURL."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import yaml

from hitman.core.curl import CurlParseError, looks_like_curl, parse_curl
from hitman.core.models import (METHODS, RAW_TYPES, Auth, Collection, Folder, KeyValue, Node,
                                Request, Variable, count_requests, iter_folders)
from hitman.core.urls import apply_params, apply_url, sync_path_vars

SUPPORTED_FORMATS = ["Hitman JSON", "Postman v2.x", "OpenAPI 3", "cURL"]


class ImportFormatError(ValueError):
    pass


@dataclass
class ImportResult:
    kind: str                       # "hitman" | "postman" | "openapi" | "curl"
    label: str                      # human description of the detected format
    collection: Collection | None = None
    request: Request | None = None  # set for cURL imports

    @property
    def title(self) -> str:
        if self.collection:
            return self.collection.name
        return self.request.name if self.request else ""

    @property
    def request_count(self) -> int:
        return count_requests(self.collection.items) if self.collection else 1

    @property
    def folder_count(self) -> int:
        return sum(1 for _ in iter_folders(self.collection.items)) if self.collection else 0


def parse_import(text: str) -> ImportResult:
    """Detect the format of `text` and parse it. Raises ImportFormatError with a readable message."""
    stripped = (text or "").strip()
    if not stripped:
        raise ImportFormatError("Nothing to import.")
    if looks_like_curl(stripped):
        try:
            return ImportResult("curl", "cURL · 1 request", request=parse_curl(stripped))
        except CurlParseError as exc:
            raise ImportFormatError(str(exc)) from exc

    data = _load_structured(stripped)
    if not isinstance(data, dict):
        raise ImportFormatError("Not a collection format we know.")
    if "hitman" in data:
        return ImportResult("hitman", "Hitman collection", collection=_from_hitman(data))
    if isinstance(data.get("info"), dict) and isinstance(data.get("item"), list):
        schema = str(data["info"].get("schema", ""))
        version = "v2.0" if "v2.0" in schema else "v2.1"
        return ImportResult("postman", f"Postman {version} collection", collection=_from_postman(data))
    if str(data.get("openapi", "")).startswith("3"):
        return ImportResult("openapi", f"OpenAPI {data['openapi']}", collection=_from_openapi(data))
    if "swagger" in data:
        raise ImportFormatError("Swagger 2.0 isn't supported. Convert the spec to OpenAPI 3 first.")
    raise ImportFormatError("Not a collection format we know.")


def _load_structured(text: str):
    try:
        return json.loads(text)
    except ValueError as json_error:
        if text[:1] in "{[":
            raise ImportFormatError(f"Invalid JSON: {json_error}") from json_error
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ImportFormatError("Unrecognized format.") from exc


def _str(value) -> str:
    return "" if value is None else str(value)


def _method(value) -> str:
    method = _str(value).upper() or "GET"
    return method if method in METHODS else "GET"


# ------------------------------------------------------------------- native

def _kv_rows(rows) -> list[KeyValue]:
    return [KeyValue(key=_str(r.get("key")), value=_str(r.get("value")),
                     description=_str(r.get("description")), enabled=r.get("enabled", True) is not False,
                     type="file" if r.get("type") == "file" else "text")
            for r in rows or [] if isinstance(r, dict)]


def _native_auth(data, default: str) -> Auth:
    if not isinstance(data, dict):
        return Auth(type=default)
    auth_type = data.get("type", default)
    if auth_type == "apikey":
        return Auth(type="apikey", key=_str(data.get("key")), value=_str(data.get("value")),
                    add_to="query" if data.get("in") == "query" else "header")
    return Auth.from_dict({**data, "type": auth_type}, default_type=default)


def _from_hitman(data: dict) -> Collection:
    info = data.get("info") or {}

    def items(nodes) -> list[Node]:
        out: list[Node] = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "folder":
                out.append(Folder(name=_str(node.get("name")) or "Folder", items=items(node.get("items"))))
                continue
            body = node.get("body") or {}
            raw_type = body.get("type", "JSON")
            req = Request(
                name=_str(node.get("name")) or "Request",
                method=_method(node.get("method")),
                url=_str(node.get("url")),
                params=_kv_rows(node.get("params")),
                path_vars=_kv_rows(node.get("pathVariables")),
                headers=_kv_rows(node.get("headers")),
                auth=_native_auth(node.get("auth"), "inherit"),
                body_mode=body.get("mode", "none") if body.get("mode") in ("raw", "form", "urlencoded") else "none",
                raw_type=raw_type if raw_type in RAW_TYPES else "JSON",
                body=_str(body.get("raw")),
                form=_kv_rows(body.get("fields")),
            )
            if not req.params:
                apply_url(req, req.url)
            out.append(req)
        return out

    return Collection(
        name=_str(info.get("name")) or "Imported collection",
        auth=_native_auth(data.get("auth"), "none"),
        variables=[Variable(key=_str(v.get("key")), value=_str(v.get("value")))
                   for v in data.get("variables") or [] if isinstance(v, dict)],
        items=items(data.get("items")),
    )


# ------------------------------------------------------------------ postman

def _pm_rows(rows) -> list[KeyValue]:
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        desc = r.get("description")
        if isinstance(desc, dict):
            desc = desc.get("content")
        out.append(KeyValue(key=_str(r.get("key")), value=_str(r.get("value")),
                            description=_str(desc), enabled=not r.get("disabled", False)))
    return out


def _pm_form_row(row: dict) -> KeyValue:
    """A Postman formdata entry; file entries keep their path ("src", sometimes a list)."""
    item = _pm_rows([row])[0]
    if row.get("type") == "file":
        src = row.get("src")
        item.value = _str(src[0] if isinstance(src, list) and src else src if isinstance(src, str) else "")
        item.type = "file"
    return item


def _pm_auth(data, default: str) -> Auth:
    if not isinstance(data, dict):
        return Auth(type=default)
    auth_type = data.get("type")

    def field(name: str) -> str:
        section = data.get(auth_type)
        if isinstance(section, list):  # v2.1: [{key, value}]
            for entry in section:
                if isinstance(entry, dict) and entry.get("key") == name:
                    return _str(entry.get("value"))
            return ""
        if isinstance(section, dict):  # v2.0: {key: value}
            return _str(section.get(name))
        return ""

    if auth_type == "noauth":
        return Auth(type="none")
    if auth_type == "bearer":
        return Auth(type="bearer", token=field("token"))
    if auth_type == "basic":
        return Auth(type="basic", username=field("username"), password=field("password"))
    if auth_type == "apikey":
        return Auth(type="apikey", key=field("key") or "X-API-Key", value=field("value"),
                    add_to="query" if field("in") == "query" else "header")
    return Auth(type=default)


def _pm_url(url) -> tuple[str, list[KeyValue], list[KeyValue]]:
    if isinstance(url, str):
        return url, [], []
    if not isinstance(url, dict):
        return "", [], []
    raw = _str(url.get("raw"))
    if not raw:
        host = url.get("host") or []
        path = url.get("path") or []
        host = ".".join(host) if isinstance(host, list) else _str(host)
        path = "/".join(_str(p) for p in path) if isinstance(path, list) else _str(path)
        protocol = url.get("protocol")
        raw = (f"{protocol}://" if protocol else "") + host + (f"/{path}" if path else "")
    return raw, _pm_rows(url.get("query")), _pm_rows(url.get("variable"))


def _pm_request(item: dict) -> Request:
    data = item.get("request")
    if isinstance(data, str):
        data = {"url": data, "method": "GET"}
    data = data or {}
    url, query, path_vars = _pm_url(data.get("url"))
    req = Request(name=_str(item.get("name")) or "Request", method=_method(data.get("method")),
                  headers=_pm_rows(data.get("header")), auth=_pm_auth(data.get("auth"), "inherit"))
    apply_url(req, url)
    if query:
        req.params = query
    known = {p.key: p for p in path_vars}
    req.path_vars = [known.get(p.key, p) for p in req.path_vars]

    body = data.get("body") or {}
    mode = body.get("mode")
    if mode == "raw":
        language = ((body.get("options") or {}).get("raw") or {}).get("language", "text")
        req.body_mode = "raw"
        req.raw_type = {"json": "JSON", "javascript": "JavaScript", "html": "HTML", "xml": "XML"}.get(language, "Text")
        req.body = _str(body.get("raw"))
    elif mode == "urlencoded":
        req.body_mode, req.form = "urlencoded", _pm_rows(body.get("urlencoded"))
    elif mode == "formdata":
        req.body_mode = "form"
        req.form = [_pm_form_row(r) for r in body.get("formdata") or [] if isinstance(r, dict)]
    elif mode == "graphql":
        gql = body.get("graphql") or {}
        req.body_mode, req.raw_type = "raw", "JSON"
        variables = gql.get("variables") or "{}"
        try:
            variables = json.loads(variables) if isinstance(variables, str) else variables
        except ValueError:
            variables = {}
        req.body = json.dumps({"query": gql.get("query", ""), "variables": variables}, indent=2)
    return req


def _from_postman(data: dict) -> Collection:
    def items(nodes) -> list[Node]:
        out: list[Node] = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("item"), list):
                out.append(Folder(name=_str(node.get("name")) or "Folder", items=items(node["item"])))
            else:
                out.append(_pm_request(node))
        return out

    return Collection(
        name=_str(data["info"].get("name")) or "Imported collection",
        auth=_pm_auth(data.get("auth"), "none"),
        variables=[Variable(key=_str(v.get("key")), value=_str(v.get("value")))
                   for v in data.get("variable") or [] if isinstance(v, dict) and v.get("key")],
        items=items(data.get("item")),
    )


# ------------------------------------------------------------------ openapi

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


class _Spec:
    def __init__(self, data: dict):
        self.data = data

    def deref(self, node, depth: int = 0):
        """Follow local $ref pointers (#/components/...)."""
        while isinstance(node, dict) and "$ref" in node and depth < 20:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                return {}
            target = self.data
            for part in ref[2:].split("/"):
                target = target.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(target, dict) else {}
            node, depth = target, depth + 1
        return node if isinstance(node, (dict, list)) else {}

    def example(self, schema, depth: int = 0):
        """Build a sample value from a JSON schema."""
        schema = self.deref(schema)
        if not isinstance(schema, dict) or depth > 6:
            return None
        if "example" in schema:
            return schema["example"]
        if "default" in schema:
            return schema["default"]
        if schema.get("enum"):
            return schema["enum"][0]
        for key in ("allOf", "oneOf", "anyOf"):
            if schema.get(key):
                if key == "allOf":
                    merged: dict = {}
                    for part in schema[key]:
                        value = self.example(part, depth + 1)
                        if isinstance(value, dict):
                            merged.update(value)
                    return merged
                return self.example(schema[key][0], depth + 1)
        kind = schema.get("type")
        if kind == "object" or "properties" in schema:
            return {name: self.example(sub, depth + 1) for name, sub in (schema.get("properties") or {}).items()}
        if kind == "array":
            return [self.example(schema.get("items", {}), depth + 1)]
        if kind == "integer":
            return 0
        if kind == "number":
            return 0.0
        if kind == "boolean":
            return False
        if kind == "string":
            fmt = schema.get("format", "")
            return {"date-time": "2024-01-01T00:00:00Z", "date": "2024-01-01", "email": "user@example.com",
                    "uuid": "00000000-0000-0000-0000-000000000000"}.get(fmt, "string")
        return None


def _server_url(data: dict) -> str:
    servers = data.get("servers") or []
    if not servers or not isinstance(servers[0], dict):
        return ""
    url = _str(servers[0].get("url"))
    for name, var in (servers[0].get("variables") or {}).items():
        url = url.replace("{" + name + "}", _str((var or {}).get("default")))
    return url.rstrip("/")


def _openapi_auth(spec: _Spec) -> Auth:
    schemes = (spec.data.get("components") or {}).get("securitySchemes") or {}
    security = spec.data.get("security") or []
    names = [name for entry in security if isinstance(entry, dict) for name in entry] or list(schemes)
    for name in names:
        scheme = spec.deref(schemes.get(name, {}))
        if scheme.get("type") == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
            return Auth.with_variables("bearer")
        if scheme.get("type") == "http" and str(scheme.get("scheme", "")).lower() == "basic":
            return Auth.with_variables("basic")
        if scheme.get("type") == "apiKey" and scheme.get("in") in ("header", "query"):
            return Auth(type="apikey", key=_str(scheme.get("name")) or "X-API-Key", value="{{apiKey}}",
                        add_to=scheme["in"])
        if scheme.get("type") == "oauth2":
            return Auth.with_variables("bearer")
    return Auth(type="none")


def _from_openapi(data: dict) -> Collection:
    spec = _Spec(data)
    info = data.get("info") or {}
    base = _server_url(data)
    collection = Collection(name=_str(info.get("title")) or "Imported API", auth=_openapi_auth(spec),
                            variables=[Variable(key="baseUrl", value=base)])
    folders: dict[str, Folder] = {}

    for path, path_item in (data.get("paths") or {}).items():
        path_item = spec.deref(path_item)
        if not isinstance(path_item, dict):
            continue
        shared_params = path_item.get("parameters") or []
        for method in _HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            req = _openapi_request(spec, str(path), method, op, shared_params)
            tags = op.get("tags") or []
            if tags:
                tag = _str(tags[0])
                if tag not in folders:
                    folders[tag] = Folder(name=tag)
                    collection.items.append(folders[tag])
                folders[tag].items.append(req)
            else:
                collection.items.append(req)
    return collection


def _openapi_request(spec: _Spec, path: str, method: str, op: dict, shared: list) -> Request:
    url_path = re.sub(r"\{([^}]+)\}", r":\1", path)
    name = _str(op.get("summary")) or _str(op.get("operationId")) or f"{method.upper()} {path}"
    req = Request(name=name, method=method.upper(), url="{{baseUrl}}" + url_path)
    sync_path_vars(req)

    params: dict[tuple, dict] = {}
    for raw in list(shared) + list(op.get("parameters") or []):
        param = spec.deref(raw)
        if isinstance(param, dict) and param.get("name"):
            params[(param.get("in"), param["name"])] = param
    path_vars = {p.key: p for p in req.path_vars}
    for (location, pname), param in params.items():
        example = param.get("example")
        if example is None:
            example = spec.example(param.get("schema", {}))
        value = _param_value(example)
        description = _str(param.get("description")).split("\n")[0][:120]
        row = KeyValue(key=pname, value=value, description=description, enabled=bool(param.get("required")))
        if location == "query":
            req.params.append(row)
        elif location == "header":
            req.headers.append(row)
        elif location == "path" and pname in path_vars:
            path_vars[pname].value, path_vars[pname].description = value, description
    if req.params:
        apply_params(req)

    body = spec.deref(op.get("requestBody", {}))
    content = body.get("content") if isinstance(body, dict) else None
    if isinstance(content, dict) and content:
        _openapi_body(spec, req, content)
    return req


def _is_binary(spec: _Spec, schema) -> bool:
    """True for file fields: `format: binary` (or base64), also inside arrays."""
    schema = spec.deref(schema)
    if not isinstance(schema, dict):
        return False
    if schema.get("format") in ("binary", "base64"):
        return True
    return schema.get("type") == "array" and _is_binary(spec, schema.get("items", {}))


def _param_value(example) -> str:
    if example is None or isinstance(example, (dict, list)):
        return ""
    if isinstance(example, bool):
        return "true" if example else "false"
    return _str(example)


def _openapi_body(spec: _Spec, req: Request, content: dict) -> None:
    json_type = next((ct for ct in content if "json" in ct), None)
    if json_type:
        media = content[json_type] or {}
        example = media.get("example")
        if example is None and isinstance(media.get("examples"), dict) and media["examples"]:
            first = spec.deref(next(iter(media["examples"].values())))
            example = first.get("value") if isinstance(first, dict) else None
        if example is None:
            example = spec.example(media.get("schema", {}))
        req.body_mode, req.raw_type = "raw", "JSON"
        req.body = json.dumps(example if example is not None else {}, indent=2, ensure_ascii=False)
        return
    for ctype, mode in (("application/x-www-form-urlencoded", "urlencoded"), ("multipart/form-data", "form")):
        if ctype in content:
            schema = spec.deref((content[ctype] or {}).get("schema", {}))
            sample = spec.example(schema)
            properties = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
            req.body_mode = mode
            if isinstance(sample, dict):
                for key, value in sample.items():
                    is_file = mode == "form" and _is_binary(spec, properties.get(key, {}))
                    text = "" if is_file or isinstance(value, (dict, list)) or value is None else _str(value)
                    req.form.append(KeyValue(key=key, value=text, type="file" if is_file else "text"))
            return
    xml_type = next((ct for ct in content if "xml" in ct), None)
    if xml_type:
        req.body_mode, req.raw_type, req.body = "raw", "XML", ""
