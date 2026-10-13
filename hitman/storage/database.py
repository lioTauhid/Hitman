"""SQLite connection and schema migrations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Each entry upgrades the schema by one version. Never edit a shipped entry; append a new one.
MIGRATIONS = [
    """
    CREATE TABLE collections (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        position    INTEGER NOT NULL DEFAULT 0,
        auth        TEXT NOT NULL DEFAULT '{}',
        variables   TEXT NOT NULL DEFAULT '[]',
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL
    );
    CREATE TABLE items (
        id            TEXT PRIMARY KEY,
        collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
        parent_id     TEXT REFERENCES items(id) ON DELETE CASCADE,
        kind          TEXT NOT NULL CHECK (kind IN ('folder', 'request')),
        name          TEXT NOT NULL,
        position      INTEGER NOT NULL DEFAULT 0,
        data          TEXT NOT NULL DEFAULT '{}',
        created_at    REAL NOT NULL,
        updated_at    REAL NOT NULL
    );
    CREATE INDEX idx_items_tree ON items (collection_id, parent_id, position);
    CREATE TABLE environments (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        color      TEXT NOT NULL DEFAULT 'ok',
        position   INTEGER NOT NULL DEFAULT 0,
        is_global  INTEGER NOT NULL DEFAULT 0,
        variables  TEXT NOT NULL DEFAULT '[]'
    );
    CREATE TABLE history (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id   TEXT,
        method       TEXT NOT NULL,
        url          TEXT NOT NULL,
        status       INTEGER,
        duration_ms  INTEGER NOT NULL DEFAULT 0,
        size         INTEGER NOT NULL DEFAULT 0,
        created_at   REAL NOT NULL,
        request      TEXT NOT NULL
    );
    CREATE INDEX idx_history_created ON history (created_at DESC);
    CREATE TABLE settings (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for index in range(version, len(MIGRATIONS)):
            with self.transaction():
                self.conn.executescript(MIGRATIONS[index])
            self.conn.execute(f"PRAGMA user_version = {index + 1}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self) -> None:
        self.conn.close()
