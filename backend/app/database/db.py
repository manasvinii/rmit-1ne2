"""Thin SQL layer over SQLite (local dev/tests) or Postgres/Supabase (pgvector).

Repositories write portable SQL with `?` placeholders; this module adapts placeholders,
JSON and vector values to the active engine.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence

import numpy as np

from app.core.config import get_settings

SCHEMA_DIR = Path(__file__).resolve().parent / "migrations"


class Database:
    def __init__(self, url: Optional[str] = None, sqlite_path: Optional[str] = None):
        settings = get_settings()
        self.url = url if url is not None else settings.database_url
        self.is_postgres = self.url.startswith("postgres")
        self._local = threading.local()
        self.sqlite_path = sqlite_path or settings.sqlite_path
        if not self.is_postgres and self.sqlite_path != ":memory:":
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------ connections
    def _connect(self):
        if self.is_postgres:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(self.url, row_factory=dict_row, autocommit=False)
            try:
                from pgvector.psycopg import register_vector

                register_vector(conn)
            except Exception:  # pragma: no cover - pgvector extension/adapter missing
                pass
            return conn
        if self.sqlite_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON")
            return self._memory_conn
        conn = sqlite3.connect(self.sqlite_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @property
    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._connect()
            self._local.conn = c
        return c

    def _sql(self, sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s") if self.is_postgres else sql

    # ------------------------------------------------------------------ execution
    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), tuple(params))
        self.conn.commit()

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        rows = [tuple(r) for r in rows]
        if not rows:
            return
        cur = self.conn.cursor()
        cur.executemany(self._sql(sql), rows)
        self.conn.commit()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
        rows = self.fetchall(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------ value adapters
    def json(self, value: Any):
        if self.is_postgres:
            from psycopg.types.json import Jsonb

            return Jsonb(value)
        return json.dumps(value, default=str)

    @staticmethod
    def load_json(value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {}

    def vector(self, values: Optional[Sequence[float]]):
        if values is None:
            return None
        arr = np.asarray(values, dtype=np.float32)
        return arr if self.is_postgres else arr.tobytes()

    @staticmethod
    def load_vector(value: Any) -> Optional[np.ndarray]:
        if value is None:
            return None
        if isinstance(value, (bytes, memoryview)):
            return np.frombuffer(bytes(value), dtype=np.float32)
        return np.asarray(value, dtype=np.float32)

    # ------------------------------------------------------------------ schema
    def init_schema(self) -> None:
        if self.is_postgres:
            for f in sorted((SCHEMA_DIR / "postgres").glob("*.sql")):
                cur = self.conn.cursor()
                cur.execute(f.read_text())
                self.conn.commit()
        else:
            self.conn.executescript((SCHEMA_DIR / "sqlite" / "schema.sql").read_text())
            self.conn.commit()


_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    global _db
    with _db_lock:
        if _db is None:
            _db = Database()
            _db.init_schema()
        return _db


def set_db(db: Optional[Database]) -> None:
    """Used by tests to inject an isolated database."""
    global _db
    _db = db
