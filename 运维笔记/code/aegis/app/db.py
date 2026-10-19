from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DatabaseIntegrityError(RuntimeError):
    """Raised for a database uniqueness or foreign-key constraint failure."""


class Database:
    """Small SQL facade with SQLite for local use and PostgreSQL for production."""

    def __init__(self, path: Path | None = None, database_url: str | None = None):
        self._postgres: PostgresDatabase | None = None
        if database_url:
            self._postgres = PostgresDatabase(database_url)
            self.path = None
            return
        if path is None:
            raise ValueError("SQLite database path or PostgreSQL database_url is required")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self._postgres is not None:
            with self._postgres.connect() as conn:
                yield conn
            return
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        if self._postgres is not None:
            self._postgres.init_schema()
            return
        with self.connect() as c:
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS principals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK(kind IN ('user','ai')),
                    key_prefix TEXT NOT NULL DEFAULT '',
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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','user')),
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_prefix TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_principal_id ON audit_events(principal_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_token_prefix ON sessions(token_prefix);
                """
            )
            self._ensure_columns(c, "servers", {
                "username": "TEXT NOT NULL DEFAULT ''",
                "port": "INTEGER NOT NULL DEFAULT 22",
                "known_hosts_path": "TEXT NOT NULL DEFAULT ''",
                "credential_ref": "TEXT NOT NULL DEFAULT ''",
            })
            self._ensure_columns(c, "principals", {
                "key_prefix": "TEXT NOT NULL DEFAULT ''",
            })
            c.execute("CREATE INDEX IF NOT EXISTS idx_principals_key_prefix ON principals(key_prefix)")

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def insert(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        if self._postgres is not None:
            return self._postgres.insert(sql, args)
        try:
            with self.connect() as c:
                cur = c.execute(sql, args)
                return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DatabaseIntegrityError("数据库约束冲突") from exc

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if self._postgres is not None:
            return self._postgres.rows(sql, args)
        with self.connect() as c:
            return [dict(row) for row in c.execute(sql, args).fetchall()]

    def row(self, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        if self._postgres is not None:
            return self._postgres.row(sql, args)
        with self.connect() as c:
            row = c.execute(sql, args).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        """Run a write statement that does not need an inserted id."""
        if self._postgres is not None:
            return self._postgres.execute(sql, args)
        try:
            with self.connect() as c:
                return int(c.execute(sql, args).rowcount)
        except sqlite3.IntegrityError as exc:
            raise DatabaseIntegrityError("数据库约束冲突") from exc

    def seed(self, seed_rules: list[dict[str, str]], seed_demo: bool) -> None:
        if self._postgres is not None:
            self._postgres.seed(seed_rules, seed_demo)
            return
        for rule in seed_rules:
            self.insert(
                "INSERT OR IGNORE INTO rules(id,name,pattern,reason,severity,created_at) VALUES(?,?,?,?,?,?)",
                (rule["id"], rule["name"], rule["pattern"], rule["reason"], rule.get("severity", "critical"), utc_now()),
            )
        if seed_demo and not self.row("SELECT id FROM servers LIMIT 1"):
            self.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,created_at) VALUES(?,?,?,?,?,?,?)", ("prod-api-01", "10.20.1.10", "production", json.dumps(["api", "critical"]), "ops", 22, utc_now()))
            self.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,created_at) VALUES(?,?,?,?,?,?,?)", ("staging-worker-01", "10.20.2.11", "staging", json.dumps(["worker"]), "ops", 22, utc_now()))


class PostgresDatabase:
    """PostgreSQL implementation using psycopg 3.

    The driver is imported only when a PostgreSQL URL is configured. Local
    SQLite tests therefore remain dependency-free; production startup fails
    clearly when the required driver is missing.
    """

    def __init__(self, database_url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("AEGIS_DATABASE_URL 使用 PostgreSQL 时需要安装 psycopg[binary]") from exc
        self.database_url = database_url
        self._psycopg = psycopg
        self._dict_row = dict_row
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        conn = self._psycopg.connect(self.database_url, row_factory=self._dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _sql(sql: str) -> str:
        statement = sql.replace("?", "%s")
        if re.match(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", statement, re.IGNORECASE):
            statement = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", statement, flags=re.IGNORECASE)
            statement += " ON CONFLICT DO NOTHING"
        elif re.match(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+access_grants\b", statement, re.IGNORECASE):
            statement = re.sub(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", statement, flags=re.IGNORECASE)
            statement += " ON CONFLICT (principal_id, server_id) DO UPDATE SET actions_json=EXCLUDED.actions_json"
        return statement

    def init_schema(self) -> None:
        with self.connect() as conn:
            schema = """
                CREATE TABLE IF NOT EXISTS principals (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK(kind IN ('user','ai')),
                    key_prefix TEXT NOT NULL DEFAULT '',
                    key_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS servers (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    address TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'production',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'online',
                    username TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 22,
                    known_hosts_path TEXT NOT NULL DEFAULT '',
                    credential_ref TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_grants (
                    principal_id BIGINT NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
                    server_id BIGINT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
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
                    id BIGSERIAL PRIMARY KEY,
                    principal_id BIGINT,
                    server_id BIGINT,
                    action TEXT NOT NULL,
                    command TEXT,
                    decision TEXT NOT NULL,
                    rule_id TEXT,
                    reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','user')),
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_prefix TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_principal_id ON audit_events(principal_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_principals_key_prefix ON principals(key_prefix);
                CREATE INDEX IF NOT EXISTS idx_sessions_token_prefix ON sessions(token_prefix);
                """
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(statement)

    def insert(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        statement = self._sql(sql)
        wants_id = bool(re.match(r"^\s*INSERT\s+INTO\s+(principals|servers|audit_events)\b", statement, re.IGNORECASE))
        if wants_id and " RETURNING " not in statement.upper():
            statement += " RETURNING id"
        try:
            with self.connect() as conn:
                cursor = conn.execute(statement, args)
                if wants_id:
                    row = cursor.fetchone()
                    return int(row["id"]) if row else 0
                return 0
        except self._psycopg.errors.IntegrityError as exc:
            raise DatabaseIntegrityError("数据库约束冲突") from exc

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(self._sql(sql), args).fetchall()]

    def row(self, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(self._sql(sql), args).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self.connect() as conn:
            return int(conn.execute(self._sql(sql), args).rowcount)

    def seed(self, seed_rules: list[dict[str, str]], seed_demo: bool) -> None:
        for rule in seed_rules:
            self.insert(
                "INSERT OR IGNORE INTO rules(id,name,pattern,reason,severity,created_at) VALUES(?,?,?,?,?,?)",
                (rule["id"], rule["name"], rule["pattern"], rule.get("reason", ""), rule.get("severity", "critical"), utc_now()),
            )
        if seed_demo and not self.row("SELECT id FROM servers LIMIT 1"):
            self.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,created_at) VALUES(?,?,?,?,?,?,?)", ("prod-api-01", "10.20.1.10", "production", json.dumps(["api", "critical"]), "ops", 22, utc_now()))
            self.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,created_at) VALUES(?,?,?,?,?,?,?)", ("staging-worker-01", "10.20.2.11", "staging", json.dumps(["worker"]), "ops", 22, utc_now()))
