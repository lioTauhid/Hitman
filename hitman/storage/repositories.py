"""Repositories: the only code that writes SQL."""

from __future__ import annotations

import json
import time

from hitman.core.models import (Auth, Collection, Environment, Folder, HistoryEntry, Node,
                                Request, Variable)
from hitman.storage.database import Database


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class CollectionRepository:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- reads
    def load_all(self) -> list[Collection]:
        conn = self.db.conn
        collections = [
            Collection(
                id=row["id"], name=row["name"],
                auth=Auth.from_dict(json.loads(row["auth"]), default_type="none"),
                variables=[Variable.from_dict(v) for v in json.loads(row["variables"])],
            )
            for row in conn.execute("SELECT * FROM collections ORDER BY position, created_at")
        ]
        by_collection = {c.id: c for c in collections}
        rows = conn.execute("SELECT * FROM items ORDER BY position, created_at").fetchall()
        nodes: dict[str, Node] = {}
        for row in rows:
            if row["kind"] == "folder":
                nodes[row["id"]] = Folder(id=row["id"], name=row["name"])
            else:
                req = Request.from_dict(json.loads(row["data"]))
                req.id, req.name = row["id"], row["name"]
                nodes[row["id"]] = req
        for row in rows:
            node = nodes[row["id"]]
            parent = nodes.get(row["parent_id"]) if row["parent_id"] else None
            if isinstance(parent, Folder):
                parent.items.append(node)
            elif row["collection_id"] in by_collection:
                by_collection[row["collection_id"]].items.append(node)
        return collections

    # --------------------------------------------------------------- writes
    def _next_position(self, table: str, where: str = "", args: tuple = ()) -> int:
        sql = f"SELECT COALESCE(MAX(position), -1) + 1 FROM {table}" + (f" WHERE {where}" if where else "")
        return self.db.conn.execute(sql, args).fetchone()[0]

    def create(self, collection: Collection) -> None:
        """Insert a collection with its whole item tree."""
        now = time.time()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO collections (id, name, position, auth, variables, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (collection.id, collection.name, self._next_position("collections"),
                 _dumps(collection.auth.to_dict()), _dumps([v.to_dict() for v in collection.variables]), now, now))
            self._insert_items(conn, collection.id, None, collection.items, now)

    def _insert_items(self, conn, collection_id: str, parent_id: str | None, items: list[Node], now: float) -> None:
        for position, node in enumerate(items):
            if isinstance(node, Folder):
                conn.execute(
                    "INSERT INTO items (id, collection_id, parent_id, kind, name, position, data, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'folder', ?, ?, '{}', ?, ?)",
                    (node.id, collection_id, parent_id, node.name, position, now, now))
                self._insert_items(conn, collection_id, node.id, node.items, now)
            else:
                conn.execute(
                    "INSERT INTO items (id, collection_id, parent_id, kind, name, position, data, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'request', ?, ?, ?, ?, ?)",
                    (node.id, collection_id, parent_id, node.name, position, _dumps(node.to_dict()), now, now))

    def update_meta(self, collection_id: str, *, name: str | None = None, auth: Auth | None = None,
                    variables: list[Variable] | None = None) -> None:
        sets, args = ["updated_at = ?"], [time.time()]
        if name is not None:
            sets.append("name = ?")
            args.append(name)
        if auth is not None:
            sets.append("auth = ?")
            args.append(_dumps(auth.to_dict()))
        if variables is not None:
            sets.append("variables = ?")
            args.append(_dumps([v.to_dict() for v in variables]))
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id = ?", (*args, collection_id))

    def delete(self, collection_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))

    def add_item(self, collection_id: str, parent_id: str | None, node: Node,
                 after_id: str | None = None) -> None:
        """Insert a folder or request at the end of its parent, or right after `after_id`."""
        now = time.time()
        with self.db.transaction() as conn:
            parent_clause = "parent_id IS ?" if parent_id is None else "parent_id = ?"
            position = None
            if after_id:
                row = conn.execute("SELECT position FROM items WHERE id = ?", (after_id,)).fetchone()
                if row:
                    position = row["position"] + 1
                    conn.execute(f"UPDATE items SET position = position + 1 WHERE collection_id = ? AND {parent_clause}"
                                 " AND position >= ?", (collection_id, parent_id, position))
            if position is None:
                position = self._next_position("items", f"collection_id = ? AND {parent_clause}",
                                               (collection_id, parent_id))
            self._insert_items(conn, collection_id, parent_id, [node], now)
            conn.execute("UPDATE items SET position = ? WHERE id = ?", (position, node.id))

    def update_request(self, request: Request) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE items SET name = ?, data = ?, updated_at = ? WHERE id = ? AND kind = 'request'",
                         (request.name, _dumps(request.to_dict()), time.time(), request.id))

    def rename_item(self, item_id: str, name: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT kind, data FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return
            data = row["data"]
            if row["kind"] == "request":
                payload = json.loads(data)
                payload["name"] = name
                data = _dumps(payload)
            conn.execute("UPDATE items SET name = ?, data = ?, updated_at = ? WHERE id = ?",
                         (name, data, time.time(), item_id))

    def delete_item(self, item_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


class EnvironmentRepository:
    def __init__(self, db: Database):
        self.db = db

    def load_all(self) -> list[Environment]:
        return [
            Environment(id=row["id"], name=row["name"], color=row["color"], is_global=bool(row["is_global"]),
                        variables=[Variable.from_dict(v) for v in json.loads(row["variables"])])
            for row in self.db.conn.execute("SELECT * FROM environments ORDER BY is_global DESC, position")
        ]

    def replace_all(self, environments: list[Environment]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM environments")
            conn.executemany(
                "INSERT INTO environments (id, name, color, position, is_global, variables) VALUES (?, ?, ?, ?, ?, ?)",
                [(e.id, e.name, e.color, i, int(e.is_global), _dumps([v.to_dict() for v in e.variables]))
                 for i, e in enumerate(environments)])


class HistoryRepository:
    MAX_ENTRIES = 500

    def __init__(self, db: Database):
        self.db = db

    def add(self, entry: HistoryEntry) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO history (request_id, method, url, status, duration_ms, size, created_at, request)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.request_id, entry.method, entry.url, entry.status, entry.duration_ms, entry.size,
                 entry.created_at, _dumps(entry.request.to_dict())))
            conn.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY created_at DESC LIMIT ?)",
                         (self.MAX_ENTRIES,))

    def list(self, limit: int = 200) -> list[HistoryEntry]:
        rows = self.db.conn.execute("SELECT * FROM history ORDER BY created_at DESC LIMIT ?", (limit,))
        return [
            HistoryEntry(id=row["id"], request_id=row["request_id"], method=row["method"], url=row["url"],
                         status=row["status"], duration_ms=row["duration_ms"], size=row["size"],
                         created_at=row["created_at"], request=Request.from_dict(json.loads(row["request"])))
            for row in rows
        ]

    def clear(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM history")


class SettingsRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default=None):
        row = self.db.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def set(self, key: str, value) -> None:
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                         " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, _dumps(value)))
