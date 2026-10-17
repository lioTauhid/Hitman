"""Plain data models shared by storage, services and the UI."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Iterator, Union

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
METHOD_SHORT = {"DELETE": "DEL", "OPTIONS": "OPT"}

AUTH_TYPES = ("inherit", "none", "bearer", "basic", "apikey")
AUTH_LABELS = {
    "inherit": "Inherit from parent",
    "none": "No auth",
    "bearer": "Bearer token",
    "basic": "Basic auth",
    "apikey": "API key",
}

BODY_MODES = ("none", "form", "urlencoded", "raw")
BODY_MODE_LABELS = {
    "none": "none",
    "form": "form-data",
    "urlencoded": "x-www-form-urlencoded",
    "raw": "raw",
}
RAW_TYPES = ("JSON", "Text", "JavaScript", "HTML", "XML")

ENV_COLORS = ("ok", "warn", "err", "put", "patch")


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]


def method_short(method: str) -> str:
    return METHOD_SHORT.get(method, method)


@dataclass
class KeyValue:
    key: str = ""
    value: str = ""          # for file rows: the path of the file to upload
    description: str = ""
    enabled: bool = True
    type: str = "text"       # "text" or "file" (files only apply to form-data bodies)

    @property
    def is_file(self) -> bool:
        return self.type == "file"

    def to_dict(self) -> dict:
        data = {"key": self.key, "value": self.value, "description": self.description, "enabled": self.enabled}
        if self.is_file:
            data["type"] = "file"
        return data

    @classmethod
    def from_dict(cls, data: dict) -> KeyValue:
        return cls(
            key=str(data.get("key", "")),
            value=str(data.get("value", "")),
            description=str(data.get("description", "")),
            enabled=bool(data.get("enabled", True)),
            type="file" if data.get("type") == "file" else "text",
        )


@dataclass
class Auth:
    type: str = "inherit"
    token: str = ""
    username: str = ""
    password: str = ""
    key: str = "X-API-Key"
    value: str = ""
    add_to: str = "header"  # "header" or "query"

    def to_dict(self) -> dict:
        return {"type": self.type, "token": self.token, "username": self.username,
                "password": self.password, "key": self.key, "value": self.value,
                "add_to": self.add_to}

    @classmethod
    def from_dict(cls, data: dict | None, default_type: str = "inherit") -> Auth:
        data = data or {}
        auth_type = data.get("type", default_type)
        return cls(
            type=auth_type if auth_type in AUTH_TYPES else default_type,
            token=str(data.get("token", "")),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            key=str(data.get("key", "X-API-Key")),
            value=str(data.get("value", "")),
            add_to="query" if data.get("add_to") == "query" else "header",
        )

    @classmethod
    def with_variables(cls, auth_type: str) -> Auth:
        """Collection auth whose credentials point at environment variables."""
        return cls(type=auth_type, token="{{accessToken}}", username="{{username}}",
                   password="{{password}}", key="X-API-Key", value="{{apiKey}}")


@dataclass
class Request:
    id: str = field(default_factory=lambda: new_id("r_"))
    name: str = "Untitled request"
    method: str = "GET"
    url: str = ""
    params: list[KeyValue] = field(default_factory=list)
    path_vars: list[KeyValue] = field(default_factory=list)
    headers: list[KeyValue] = field(default_factory=list)
    auth: Auth = field(default_factory=Auth)
    body_mode: str = "none"
    raw_type: str = "JSON"
    body: str = ""
    form: list[KeyValue] = field(default_factory=list)

    def copy(self) -> Request:
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "method": self.method, "url": self.url,
            "params": [p.to_dict() for p in self.params],
            "path_vars": [p.to_dict() for p in self.path_vars],
            "headers": [h.to_dict() for h in self.headers],
            "auth": self.auth.to_dict(),
            "body_mode": self.body_mode, "raw_type": self.raw_type, "body": self.body,
            "form": [f.to_dict() for f in self.form],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Request:
        method = str(data.get("method", "GET")).upper()
        body_mode = data.get("body_mode", "none")
        raw_type = data.get("raw_type", "JSON")
        return cls(
            id=str(data.get("id") or new_id("r_")),
            name=str(data.get("name", "Untitled request")),
            method=method if method in METHODS else "GET",
            url=str(data.get("url", "")),
            params=[KeyValue.from_dict(p) for p in data.get("params", [])],
            path_vars=[KeyValue.from_dict(p) for p in data.get("path_vars", [])],
            headers=[KeyValue.from_dict(h) for h in data.get("headers", [])],
            auth=Auth.from_dict(data.get("auth")),
            body_mode=body_mode if body_mode in BODY_MODES else "none",
            raw_type=raw_type if raw_type in RAW_TYPES else "JSON",
            body=str(data.get("body", "")),
            form=[KeyValue.from_dict(f) for f in data.get("form", [])],
        )


@dataclass
class Folder:
    id: str = field(default_factory=lambda: new_id("f_"))
    name: str = "New folder"
    items: list[Node] = field(default_factory=list)


Node = Union[Folder, Request]


@dataclass
class Variable:
    key: str = ""
    value: str = ""
    enabled: bool = True
    secret: bool = False

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value,
                "enabled": self.enabled, "secret": self.secret}

    @classmethod
    def from_dict(cls, data: dict) -> Variable:
        return cls(key=str(data.get("key", "")), value=str(data.get("value", "")),
                   enabled=bool(data.get("enabled", True)), secret=bool(data.get("secret", False)))


@dataclass
class Collection:
    id: str = field(default_factory=lambda: new_id("c_"))
    name: str = "New collection"
    auth: Auth = field(default_factory=lambda: Auth(type="none"))
    variables: list[Variable] = field(default_factory=list)
    items: list[Node] = field(default_factory=list)

    def copy(self) -> Collection:
        return copy.deepcopy(self)


@dataclass
class Environment:
    id: str = field(default_factory=lambda: new_id("e_"))
    name: str = "New environment"
    color: str = "put"
    variables: list[Variable] = field(default_factory=list)
    is_global: bool = False

    def copy(self) -> Environment:
        return copy.deepcopy(self)


@dataclass
class HistoryEntry:
    method: str
    url: str
    status: int | None
    duration_ms: int
    size: int
    created_at: float
    request: Request
    request_id: str | None = None
    id: int | None = None


# ---------------------------------------------------------------- tree helpers

def iter_requests(items: list[Node]) -> Iterator[Request]:
    for node in items:
        if isinstance(node, Folder):
            yield from iter_requests(node.items)
        else:
            yield node


def count_requests(items: list[Node]) -> int:
    return sum(1 for _ in iter_requests(items))


def iter_folders(items: list[Node], depth: int = 0) -> Iterator[tuple[Folder, int]]:
    """Yield (folder, depth) pairs in tree order."""
    for node in items:
        if isinstance(node, Folder):
            yield node, depth
            yield from iter_folders(node.items, depth + 1)


def find_path(items: list[Node], node_id: str) -> list[Node] | None:
    """Return the chain of nodes from the top level down to node_id."""
    for node in items:
        if node.id == node_id:
            return [node]
        if isinstance(node, Folder):
            sub = find_path(node.items, node_id)
            if sub is not None:
                return [node, *sub]
    return None


def regenerate_ids(items: list[Node]) -> None:
    """Give every node in the tree a fresh id (used when duplicating)."""
    for node in items:
        if isinstance(node, Folder):
            node.id = new_id("f_")
            regenerate_ids(node.items)
        else:
            node.id = new_id("r_")
