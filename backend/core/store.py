"""Persistence for trades / bot_logs / backtest_results / suggestions.

Primary backend: Neon (serverless Postgres) via psycopg 3 and a small connection pool.
Fallback: a local SQLite file, used automatically when DATABASE_URL isn't set, so the app is
fully usable on day one. The UI shows which store is active.
"""
from __future__ import annotations

import atexit
import json
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from core.config import BACKEND_DIR, DATA_DIR, get_settings
from core.timeutil import utc_now_iso

# column whitelist per table (also the contract with backend/migrations/0001_init.sql)
SCHEMA: dict[str, dict[str, Any]] = {
    "trades": {
        "cols": ["id", "created_at", "instrument", "action", "quantity", "price", "order_id", "status",
                 "strategy_tag", "pnl", "is_paper", "meta"],
        "json": {"meta"},
        "bool": {"is_paper"},
    },
    "bot_logs": {"cols": ["id", "created_at", "level", "message"], "json": set(), "bool": set()},
    "backtest_results": {
        "cols": ["id", "created_at", "strategy", "instrument", "params", "metrics_json", "trades_json"],
        "json": {"params", "metrics_json", "trades_json"},
        "bool": set(),
    },
    "suggestions": {
        "cols": ["id", "created_at", "symbol", "model", "context_json", "setups_json"],
        "json": {"context_json", "setups_json"},
        "bool": set(),
    },
    "activity_logs": {
        "cols": ["id", "created_at", "category", "action", "summary", "level", "details"],
        "json": {"details"},
        "bool": set(),
    },
}

Filter = tuple[str, str, Any]  # (column, op, value) ; op in eq|gt|gte|lt|lte
_OPS = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class StoreError(RuntimeError):
    pass


def _check(table: str, cols: list[str]) -> None:
    if table not in SCHEMA:
        raise StoreError(f"unknown table {table}")
    bad = [c for c in cols if c not in SCHEMA[table]["cols"]]
    if bad:
        raise StoreError(f"unknown column(s) {bad} for {table}")


class Store(ABC):
    kind: str

    @abstractmethod
    def insert(self, table: str, row: dict) -> dict: ...

    @abstractmethod
    def update(self, table: str, row_id: str, patch: dict) -> None: ...

    @abstractmethod
    def select(
        self,
        table: str,
        filters: list[Filter] | None = None,
        order: str | None = "created_at",
        desc: bool = True,
        limit: int = 1000,
        offset: int = 0,
        columns: list[str] | None = None,
    ) -> list[dict]: ...

    def select_all(self, table: str, filters: list[Filter] | None = None, order: str | None = "created_at",
                   desc: bool = True, columns: list[str] | None = None, cap: int = 20000) -> list[dict]:
        """Page through results, 1000 rows at a time."""
        out: list[dict] = []
        page = 1000
        while len(out) < cap:
            rows = self.select(table, filters, order, desc, limit=page, offset=len(out), columns=columns)
            out.extend(rows)
            if len(rows) < page:
                break
        return out

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self.select("bot_logs", limit=1)
            return True, "ok"
        except Exception as e:  # noqa: BLE001 - report whatever went wrong
            return False, str(e)[:200]


# ----------------------------------------------------------------------------- SQLite
class SqliteStore(Store):
    kind = "sqlite"

    _DDL = """
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, instrument TEXT NOT NULL, action TEXT NOT NULL,
        quantity INTEGER NOT NULL, price REAL NOT NULL, order_id TEXT, status TEXT NOT NULL,
        strategy_tag TEXT, pnl REAL, is_paper INTEGER NOT NULL DEFAULT 1, meta TEXT);
    CREATE INDEX IF NOT EXISTS trades_created_idx ON trades(created_at);
    CREATE TABLE IF NOT EXISTS bot_logs (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS bot_logs_created_idx ON bot_logs(created_at);
    CREATE TABLE IF NOT EXISTS backtest_results (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, strategy TEXT NOT NULL, instrument TEXT NOT NULL,
        params TEXT, metrics_json TEXT, trades_json TEXT);
    CREATE TABLE IF NOT EXISTS suggestions (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, model TEXT,
        context_json TEXT, setups_json TEXT);
    CREATE TABLE IF NOT EXISTS activity_logs (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, category TEXT NOT NULL, action TEXT NOT NULL,
        summary TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'INFO', details TEXT);
    CREATE INDEX IF NOT EXISTS activity_logs_created_idx ON activity_logs(created_at);
    """

    def __init__(self, path=None):
        self.path = str(path or DATA_DIR / "axiom.db")
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(self._DDL)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        return c

    def _encode(self, table: str, row: dict) -> dict:
        spec = SCHEMA[table]
        out = {}
        for k, v in row.items():
            if k in spec["json"] and v is not None:
                v = json.dumps(v, default=str)
            elif k in spec["bool"]:
                v = int(bool(v))
            out[k] = v
        return out

    def _decode(self, table: str, r: sqlite3.Row) -> dict:
        spec = SCHEMA[table]
        d = dict(r)
        for k in spec["json"]:
            if d.get(k):
                d[k] = json.loads(d[k])
        for k in spec["bool"]:
            if k in d:
                d[k] = bool(d[k])
        return d

    def insert(self, table: str, row: dict) -> dict:
        row = {"id": str(uuid.uuid4()), "created_at": utc_now_iso(), **row}
        _check(table, list(row))
        enc = self._encode(table, row)
        cols = ", ".join(enc)
        marks = ", ".join("?" for _ in enc)
        with self._lock, self._conn() as c:
            c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(enc.values()))  # noqa: S608 - cols whitelisted
        return row

    def update(self, table: str, row_id: str, patch: dict) -> None:
        _check(table, list(patch))
        enc = self._encode(table, patch)
        sets = ", ".join(f"{k} = ?" for k in enc)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*enc.values(), row_id])  # noqa: S608

    def select(self, table, filters=None, order="created_at", desc=True, limit=1000, offset=0, columns=None):
        _check(table, [f[0] for f in filters or []] + ([order] if order else []) + (columns or []))
        where, args = [], []
        for col, op, val in filters or []:
            if op not in _OPS:
                raise StoreError(f"bad op {op}")
            where.append(f"{col} {_OPS[op]} ?")
            args.append(int(val) if col in SCHEMA[table]["bool"] else val)
        sql = f"SELECT {', '.join(columns) if columns else '*'} FROM {table}"  # noqa: S608 - table/cols whitelisted above
        if where:
            sql += " WHERE " + " AND ".join(where)
        if order:
            sql += f" ORDER BY {order} {'DESC' if desc else 'ASC'}"
        sql += " LIMIT ? OFFSET ?"
        with self._conn() as c:
            rows = c.execute(sql, [*args, limit, offset]).fetchall()
        return [self._decode(table, r) for r in rows]


# ----------------------------------------------------------------------------- Neon (Postgres)
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
_SCHEMA_LOCK_ID = 0x41584D  # "AXM": serialises schema setup when the API and the bot start at once
_POOL_TIMEOUT_S = 20
# prepare_threshold=None: no server-side prepared statements, so Neon's pooled (PgBouncer) endpoint is safe.
_CONNECT_KWARGS: dict[str, Any] = {"connect_timeout": 10, "prepare_threshold": None}


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _is_uuid(v: Any) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False


def _decode_pg(row: dict) -> dict:
    """Match the shapes the rest of the app expects: ISO-8601 UTC strings for timestamps (whatever the
    session's TimeZone is), str for uuids."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            v = v.astimezone(timezone.utc).isoformat()
        elif isinstance(v, uuid.UUID):
            v = str(v)
        out[k] = v
    return out


class PostgresStore(Store):
    kind = "neon"

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._ready = False
        self._schema_lock = threading.Lock()
        # min_size=0: nothing connects until the first query, so a missing/asleep database never blocks startup.
        # check=...: Neon suspends idle computes, so verify a pooled connection is alive before handing it out.
        self._pool = ConnectionPool(
            dsn, min_size=0, max_size=4, open=False, timeout=_POOL_TIMEOUT_S, check=ConnectionPool.check_connection,
            kwargs={**_CONNECT_KWARGS, "row_factory": dict_row},
        )
        self._pool.open()
        atexit.register(self._pool.close)  # else the pool's __del__ tries to join its threads mid-shutdown and prints a traceback

    def _ensure_schema(self) -> None:
        """Apply backend/migrations/*.sql once per process. Idempotent, like SqliteStore's CREATE IF NOT EXISTS."""
        with self._schema_lock:
            if self._ready:
                return
            files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            if not files:
                raise StoreError(f"no migrations found in {MIGRATIONS_DIR}")
            ddl = "\n".join(f.read_text(encoding="utf-8") for f in files)
            # A direct connection (not the pool) so auth / DNS / SSL problems surface as themselves
            # instead of as a generic pool timeout.
            with psycopg.connect(self._dsn, **_CONNECT_KWARGS) as c:
                c.execute("SELECT pg_advisory_xact_lock(%s)", [_SCHEMA_LOCK_ID])
                c.execute(ddl)
            self._ready = True

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection]:
        try:
            self._ensure_schema()
            with self._pool.connection() as c:  # commits on success, rolls back on error
                yield c
        except PoolTimeout as e:
            raise StoreError(f"Neon: no database connection within {_POOL_TIMEOUT_S}s — check DATABASE_URL and the project's status") from e
        except psycopg.Error as e:
            raise StoreError(f"Neon: {str(e).strip()[:300]}") from e

    @staticmethod
    def _encode(table: str, col: str, value: Any) -> Any:
        return Jsonb(value, dumps=_dumps) if col in SCHEMA[table]["json"] and value is not None else value

    def insert(self, table: str, row: dict) -> dict:
        _check(table, list(row))
        marks = ", ".join("%s" for _ in row)
        sql = f"INSERT INTO {table} ({', '.join(row)}) VALUES ({marks}) RETURNING *"  # noqa: S608 - cols whitelisted
        with self._conn() as c:
            saved = c.execute(sql, [self._encode(table, k, v) for k, v in row.items()]).fetchone()
        return _decode_pg(saved)

    def update(self, table: str, row_id: str, patch: dict) -> None:
        _check(table, list(patch))
        sets = ", ".join(f"{k} = %s" for k in patch)
        with self._conn() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE id = %s", [*(self._encode(table, k, v) for k, v in patch.items()), row_id])  # noqa: S608

    def select(self, table, filters=None, order="created_at", desc=True, limit=1000, offset=0, columns=None):
        _check(table, [f[0] for f in filters or []] + ([order] if order else []) + (columns or []))
        where, args = [], []
        for col, op, val in filters or []:
            if op not in _OPS:
                raise StoreError(f"bad op {op}")
            if col == "id" and not _is_uuid(val):
                return []  # can't match any row, and Postgres would raise on the uuid cast
            where.append(f"{col} {_OPS[op]} %s")
            args.append(val)
        sql = f"SELECT {', '.join(columns) if columns else '*'} FROM {table}"  # noqa: S608 - table/cols whitelisted above
        if where:
            sql += " WHERE " + " AND ".join(where)
        if order:
            direction = "DESC" if desc else "ASC"
            sql += f" ORDER BY {order} {direction}"
            if order != "id":
                sql += f", id {direction}"  # tie-break, so paging through equal timestamps is stable
        sql += " LIMIT %s OFFSET %s"
        with self._conn() as c:
            rows = c.execute(sql, [*args, limit, offset]).fetchall()
        return [_decode_pg(r) for r in rows]


# ----------------------------------------------------------------------------- factory
_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            s = get_settings()
            _store = PostgresStore(s.database_url.strip()) if s.database_configured else SqliteStore()
        return _store


def reset_store_for_tests(store: Store | None = None) -> None:
    global _store
    _store = store
