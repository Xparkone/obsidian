from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS principals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK(kind IN ('user','ai')),
                    key_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    address TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'production',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'online',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_grants (
                    principal_id INTEGER NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
                    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
                    actions_json TEXT NOT NULL DEFAULT '["read"]',
                    PRIMARY KEY(principal_id, server_id)
                );
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'critical',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    principal_id INTEGER,
                    server_id INTEGER,
                    action TEXT NOT NULL,
                    command TEXT,
                    decision TEXT NOT NULL,
                    rule_id TEXT,
                    reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at DESC);
                """
            )
            self._ensure_columns(c, "servers", {
                "username": "TEXT NOT NULL DEFAULT ''",
                "port": "INTEGER NOT NULL DEFAULT 22",
                "known_hosts_path": "TEXT NOT NULL DEFAULT ''",
                "credential_ref": "TEXT NOT NULL DEFAULT ''",
            })

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def insert(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self.connect() as c:
            cur = c.execute(sql, args)
            return int(cur.lastrowid)

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as c:
            return [dict(row) for row in c.execute(sql, args).fetchall()]

    def row(self, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def seed(self, seed_rules: list[dict[str, str]], seed_demo: bool) -> None:
        for rule in seed_rules:
            self.insert(
                "INSERT OR IGNORE INTO rules(id,name,pattern,reason,severity,created_at) VALUES(?,?,?,?,?,?)",
                (rule["id"], rule["name"], rule["pattern"], rule["reason"], rule.get("severity", "critical"), utc_now()),
            )
        if seed_demo and not self.row("SELECT id FROM servers LIMIT 1"):
            self.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,created_at) VALUES(?,?,?,?,?,?,?)", ("prod-api-01", "10.20.1.10", "production", json.dumps(["api", "critical"]), "ops", 22, utc_now()))
            self.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,created_at) VALUES(?,?,?,?,?,?,?)", ("staging-worker-01", "10.20.2.11", "staging", json.dumps(["worker"]), "ops", 22, utc_now()))
