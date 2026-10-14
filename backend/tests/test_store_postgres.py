"""PostgresStore (Neon).

The integration tests need a real Postgres and are skipped unless AXIOM_TEST_DATABASE_URL is set. Point it at a
throwaway database — a Neon branch is ideal: the tests create the Axiom tables there and delete their own rows.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from core import store as store_mod
from core.config import Settings
from core.store import PostgresStore, SqliteStore, StoreError, _decode_pg, _is_uuid
from core.timeutil import utc_now_iso

TEST_URL = os.getenv("AXIOM_TEST_DATABASE_URL", "")
needs_pg = pytest.mark.skipif(not TEST_URL, reason="AXIOM_TEST_DATABASE_URL not set")


# ------------------------------------------------------------------ no database needed
def test_decode_pg_returns_iso_strings_and_str_uuids():
    uid = uuid.uuid4()
    ts = datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc)
    out = _decode_pg({"id": uid, "created_at": ts, "price": 1.5, "meta": {"a": 1}, "pnl": None})
    assert out == {"id": str(uid), "created_at": "2026-10-14T04:30:00+00:00", "price": 1.5, "meta": {"a": 1}, "pnl": None}


def test_decode_pg_normalises_timestamps_to_utc_whatever_the_session_timezone():
    ist = datetime(2026, 10, 14, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert _decode_pg({"created_at": ist})["created_at"] == "2026-10-14T04:30:00+00:00"


def test_is_uuid():
    assert _is_uuid(str(uuid.uuid4())) and _is_uuid(uuid.uuid4())
    assert not _is_uuid("nope") and not _is_uuid("") and not _is_uuid("1; DROP TABLE trades")


def test_database_configured_ignores_blank_values():
    assert not Settings(database_url="", _env_file=None).database_configured
    assert not Settings(database_url="   ", _env_file=None).database_configured
    assert Settings(database_url="postgresql://u:p@h/db", _env_file=None).database_configured


def test_factory_picks_store_from_settings(monkeypatch):
    class Cfg:
        database_configured = False
        database_url = ""

    monkeypatch.setattr(store_mod, "get_settings", lambda: Cfg)
    store_mod.reset_store_for_tests()
    try:
        assert isinstance(store_mod.get_store(), SqliteStore)
        Cfg.database_configured, Cfg.database_url = True, "  postgresql://u:p@127.0.0.1:1/db  "
        store_mod.reset_store_for_tests()
        s = store_mod.get_store()
        assert isinstance(s, PostgresStore) and s.kind == "neon"
    finally:
        store_mod.reset_store_for_tests()


def test_unreachable_database_raises_store_error_and_healthcheck_reports_it():
    s = PostgresStore("postgresql://u:p@127.0.0.1:1/db?connect_timeout=2")  # nothing listens on port 1
    with pytest.raises(StoreError, match="Neon"):
        s.select("trades")
    ok, detail = s.healthcheck()
    assert not ok and detail


def test_validation_happens_before_any_connection():
    s = PostgresStore("postgresql://u:p@127.0.0.1:1/db?connect_timeout=2")
    with pytest.raises(StoreError, match="unknown table"):
        s.select("users")
    with pytest.raises(StoreError, match="unknown column"):
        s.select("trades", [("nope; DROP TABLE trades", "eq", 1)])
    with pytest.raises(StoreError, match="unknown column"):
        s.insert("trades", {"instrument": "x", "evil": 1})


# ------------------------------------------------------------------ real Postgres
@pytest.fixture
def pg():
    s = PostgresStore(TEST_URL)
    tag = f"pgtest-{uuid.uuid4().hex[:8]}"
    yield s, tag
    with psycopg.connect(TEST_URL) as c:
        c.execute("DELETE FROM trades WHERE strategy_tag = %s", [tag])
        c.execute("DELETE FROM backtest_results WHERE strategy = %s", [tag])
        c.execute("DELETE FROM suggestions WHERE symbol = %s", [tag])
        c.execute("DELETE FROM bot_logs WHERE message = %s", [tag])
        c.execute("DELETE FROM activity_logs WHERE summary = %s", [tag])


def _trade(tag: str, i: int, **over) -> dict:
    return {"instrument": "NIFTY 1 PE", "action": "SELL", "quantity": 65, "price": 10 + i, "status": "complete",
            "strategy_tag": tag, "pnl": None if i % 2 == 0 else float(i), "is_paper": i < 3, "meta": {"reason": f"r{i}"}, **over}


@needs_pg
def test_pg_roundtrip_filters_bools_json_and_paging(pg):
    s, tag = pg
    for i in range(5):
        s.insert("trades", _trade(tag, i))
    mine = [("strategy_tag", "eq", tag)]
    rows = s.select("trades", mine)
    assert len(rows) == 5
    # shapes the rest of the app relies on
    r = rows[0]
    assert isinstance(r["id"], str) and uuid.UUID(r["id"])
    assert isinstance(r["created_at"], str) and datetime.fromisoformat(r["created_at"]).tzinfo is not None
    assert isinstance(r["price"], float) and isinstance(r["quantity"], int) and r["meta"]["reason"].startswith("r")

    paper = s.select("trades", [*mine, ("is_paper", "eq", True)])
    assert len(paper) == 3 and all(x["is_paper"] is True for x in paper)
    assert s.select("trades", [*mine, ("price", "gte", 12)], order="price", desc=False)[0]["price"] == 12
    assert [x["price"] for x in s.select("trades", mine, order="price", desc=False, limit=2, offset=2)] == [12, 13]
    assert len(s.select_all("trades", mine)) == 5
    assert s.select("trades", mine, columns=["id", "price"], limit=1)[0].keys() == {"id", "price"}


@needs_pg
def test_pg_insert_honours_explicit_created_at_and_time_filters(pg):
    s, tag = pg
    s.insert("trades", _trade(tag, 0, created_at="2026-01-05T10:00:00+00:00"))
    s.insert("trades", _trade(tag, 1, created_at="2026-01-06T10:00:00+00:00"))
    got = s.select("trades", [("strategy_tag", "eq", tag), ("created_at", "gte", "2026-01-06T00:00:00+00:00")])
    assert len(got) == 1 and got[0]["created_at"] == "2026-01-06T10:00:00+00:00"
    both = s.select("trades", [("strategy_tag", "eq", tag), ("created_at", "lt", utc_now_iso())], desc=False)
    assert [x["created_at"][:10] for x in both] == ["2026-01-05", "2026-01-06"]


@needs_pg
def test_pg_json_columns_roundtrip_nested_and_unicode(pg):
    s, tag = pg
    cfg = {"strategy": tag, "params": {"fast": 9, "slow": 21}, "note": "₹ 5,000 — नमस्ते", "list": [1, 2.5, None, True]}
    saved = s.insert("backtest_results", {"strategy": tag, "instrument": "NIFTY", "params": cfg,
                                          "metrics_json": {"net": -12.5}, "trades_json": {"trades": [], "equity": [1, 2]}})
    got = s.select("backtest_results", [("id", "eq", saved["id"])], limit=1)[0]
    assert got["params"] == cfg and got["metrics_json"] == {"net": -12.5} and got["trades_json"]["equity"] == [1, 2]
    # values json can't encode natively fall back to str, like the SQLite store
    odd = s.insert("trades", _trade(tag, 0, meta={"when": datetime(2026, 1, 1, tzinfo=timezone.utc)}))
    assert isinstance(odd["meta"]["when"], str)


@needs_pg
def test_pg_update_and_missing_or_malformed_ids(pg):
    s, tag = pg
    row = s.insert("trades", _trade(tag, 1, status="open", pnl=None))
    s.update("trades", row["id"], {"status": "complete", "pnl": 99.5, "meta": {"reason": "patched"}})
    got = s.select("trades", [("id", "eq", row["id"])])[0]
    assert (got["status"], got["pnl"], got["meta"]) == ("complete", 99.5, {"reason": "patched"})
    assert s.select("trades", [("id", "eq", str(uuid.uuid4()))]) == []
    assert s.select("trades", [("id", "eq", "not-a-uuid")]) == []  # would be a 500 if it reached Postgres


@needs_pg
def test_pg_constraints_surface_as_store_error_and_pool_recovers(pg):
    s, tag = pg
    with pytest.raises(StoreError, match="Neon"):
        s.insert("trades", _trade(tag, 0, action="HOLD"))  # violates the BUY/SELL check
    with pytest.raises(StoreError):
        s.insert("trades", _trade(tag, 0, quantity=0))
    assert s.insert("trades", _trade(tag, 0))["strategy_tag"] == tag  # a failed statement doesn't poison the pool


@needs_pg
def test_pg_activity_logs_roundtrip_with_and_without_details(pg):
    s, tag = pg
    s.insert("activity_logs", {"category": "system", "action": "t", "summary": tag, "details": {"a": [1, 2], "b": "₹ — नमस्ते"}})
    s.insert("activity_logs", {"category": "system", "action": "t", "summary": tag, "level": "WARN"})
    rows = s.select("activity_logs", [("summary", "eq", tag)], order="created_at", desc=False)
    assert [r["level"] for r in rows] == ["INFO", "WARN"]  # the column default applies when level is omitted
    assert rows[0]["details"] == {"a": [1, 2], "b": "₹ — नमस्ते"} and rows[1]["details"] is None
    assert isinstance(rows[0]["created_at"], str) and rows[0]["created_at"].endswith("+00:00")


@needs_pg
def test_pg_healthcheck_and_idempotent_schema(pg):
    s, tag = pg
    assert s.healthcheck() == (True, "ok")
    again = PostgresStore(TEST_URL)  # a second process (e.g. the bot) applying the same migrations is a no-op
    again.insert("bot_logs", {"level": "INFO", "message": tag})
    assert s.select("bot_logs", [("message", "eq", tag)])[0]["level"] == "INFO"
