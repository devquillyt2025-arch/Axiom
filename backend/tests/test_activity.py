"""Activity log + Logs API: redaction, async writing, merging the three sources, paging, and what gets logged."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core import activity, store as store_mod
from core.activity import redact
from core.store import SqliteStore

H = {"X-Axiom": "1"}


@pytest.fixture
def store(tmp_path):
    activity.flush()  # anything queued by earlier tests must not land in this test's store
    s = SqliteStore(tmp_path / "act.db")
    store_mod.reset_store_for_tests(s)
    yield s
    activity.flush()
    store_mod.reset_store_for_tests()


@pytest.fixture
def client(store):
    from main import app

    return TestClient(app)


def stored(store, **where) -> list[dict]:
    activity.flush()
    rows = store.select("activity_logs", [(k, "eq", v) for k, v in where.items()], order="created_at", desc=False, limit=500)
    return rows


# ------------------------------------------------------------------ redaction
def test_redact_masks_credentials_but_not_innocent_keys():
    out = redact({
        "access_token": "abc", "API_SECRET": "x", "Authorization": "Bearer q", "password": "p", "code": "123", "state": "s",
        "instrument_key": "NSE_FO|1", "lots": 2, "nested": {"refresh_token": "r", "fine": [1, {"api-key": "k", "ok": True}]},
        "db": "connect postgresql://neondb_owner:pw@ep-x.neon.tech/db?sslmode=require now",
        "jwt": "see eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef123456 here",
    })
    assert out["access_token"] == out["API_SECRET"] == out["Authorization"] == out["password"] == out["code"] == out["state"] == "[redacted]"
    assert out["nested"]["refresh_token"] == "[redacted]" and out["nested"]["fine"][1] == {"api-key": "[redacted]", "ok": True}
    assert out["instrument_key"] == "NSE_FO|1" and out["lots"] == 2
    assert "pw@" not in out["db"] and "[redacted]" in out["db"] and "eyJ" not in out["jwt"] and "here" in out["jwt"]


def test_redact_caps_long_strings_and_depth():
    assert len(redact("x" * 5000)) <= 501
    deep: dict = {}
    cur = deep
    for _ in range(20):
        cur["n"] = {}
        cur = cur["n"]
    assert "…" in json.dumps(redact(deep), ensure_ascii=False)


# ------------------------------------------------------------------ writer
def test_record_is_written_redacted_deduped_and_normalised(store):
    activity.record("bot", "start", "Bot started", details={"api_key": "zzz", "lots": 1})
    activity.record("bot", "error", "same thing", dedupe_s=60)
    activity.record("bot", "error", "same thing", dedupe_s=60)  # suppressed
    activity.record("not-a-category", "x", "odd one", level="LOUD")
    rows = stored(store)
    assert [r["summary"] for r in rows] == ["Bot started", "same thing", "odd one"]
    assert rows[0]["details"] == {"api_key": "[redacted]", "lots": 1}
    assert (rows[2]["category"], rows[2]["level"]) == ("system", "INFO")


def test_oversized_details_are_replaced_not_stored(store):
    activity.record("system", "big", "huge payload", details={"blob": ["x" * 400] * 100})
    assert stored(store)[0]["details"] == {"_truncated": True, "note": "details too large to store"}


# ------------------------------------------------------------------ Logs API
def _seed(store):
    store.insert("activity_logs", {"created_at": "2026-10-14T10:00:01+00:00", "category": "backtest", "action": "run", "summary": "BT run", "level": "INFO", "details": {"n": 1}})
    store.insert("bot_logs", {"created_at": "2026-10-14T10:00:02+00:00", "level": "WARN", "message": "engine warning"})
    store.insert("trades", {"created_at": "2026-10-14T10:00:03+00:00", "instrument": "NIFTY 24500 PE 20 OCT 26", "action": "SELL", "quantity": 65,
                            "price": 101.2, "status": "complete", "strategy_tag": "t", "pnl": 730.0, "is_paper": True, "meta": {"reason": "target"}})
    store.insert("activity_logs", {"created_at": "2026-10-14T10:00:04+00:00", "category": "navigation", "action": "view", "summary": "Opened Bot", "level": "INFO", "details": None})


def test_logs_merges_sources_newest_first_and_filters(client, store):
    _seed(store)
    r = client.get("/logs", params={"range": "all"}).json()
    assert [(e["source"], e["category"]) for e in r["entries"]] == [("activity", "navigation"), ("trade", "trade"), ("bot", "engine"), ("activity", "backtest")]
    trade = r["entries"][1]
    assert trade["summary"] == "SELL NIFTY 24500 PE 20 OCT 26 ×65 @ 101.20 · paper · P&L +730.00 · target"
    assert trade["details"]["is_paper"] is True and trade["level"] == "INFO"

    only = lambda **q: [e["summary"] for e in client.get("/logs", params={"range": "all", **q}).json()["entries"]]  # noqa: E731
    assert only(category="engine") == ["engine warning"]
    assert only(category="trade") == [trade["summary"]]
    assert only(category="backtest") == ["BT run"]
    assert only(level="WARN") == ["engine warning"]
    assert only(level="ERROR") == []
    assert trade["summary"] not in only(level="WARN")


def test_logs_paging_walks_every_entry_once(client, store):
    _seed(store)
    seen, before = [], None
    for _ in range(10):
        r = client.get("/logs", params={"range": "all", "limit": 2, **({"before": before} if before else {})}).json()
        seen += [e["summary"] for e in r["entries"]]
        before = r["next_before"]
        if not before:
            break
    assert len(seen) == 4 and len(set(seen)) == 4
    assert seen[0] == "Opened Bot" and seen[-1] == "BT run"


def test_logs_rejects_bad_input(client):
    assert client.get("/logs", params={"before": "garbage"}).status_code == 400
    assert client.get("/logs", params={"category": "bogus"}).status_code == 422
    assert client.get("/logs", params={"limit": 0}).status_code == 422


def test_client_events_need_the_csrf_header_and_an_allowed_category(client, store):
    body = {"category": "navigation", "action": "view", "summary": "Opened Backtest", "details": {"path": "/backtest"}}
    assert client.post("/logs/event", json=body).status_code == 403  # no X-Axiom header
    assert client.post("/logs/event", json=body, headers=H).json() == {"ok": True}
    assert client.post("/logs/event", json={**body, "category": "bot"}, headers=H).status_code == 422  # only the browser's own events
    assert client.post("/logs/event", json={**body, "summary": "x" * 301}, headers=H).status_code == 422
    rows = stored(store)
    assert [(r["category"], r["summary"], r["details"]) for r in rows] == [("navigation", "Opened Backtest", {"path": "/backtest"})]


# ------------------------------------------------------------------ what gets logged
def test_failures_are_logged_centrally_and_deduped_while_polled_paths_stay_quiet(client, store):
    for _ in range(2):
        assert client.post("/bot/start", json={"strategy": "no_such_strategy"}, headers=H).status_code == 400
    assert client.get("/logs", params={"before": "garbage"}).status_code == 400  # /logs is polled: never logged
    rows = stored(store)
    assert len(rows) == 1
    assert (rows[0]["category"], rows[0]["action"], rows[0]["level"]) == ("bot", "error", "WARN")
    assert rows[0]["summary"].startswith("POST /bot/start → 400:") and rows[0]["details"]["status"] == 400
    assert activity.is_quiet("/status") and activity.is_quiet("/market/live") and activity.is_quiet("/logs") and not activity.is_quiet("/backtest")


def test_backtest_run_is_logged_with_a_readable_summary(client, store):
    body = {"strategy": "heikin_ashi", "symbol": "NIFTY", "start": "2026-09-01", "end": "2026-09-11"}
    res = client.post("/backtest", json=body, headers=H)
    assert res.status_code == 200, res.text
    (row,) = stored(store, category="backtest")
    assert row["action"] == "run" and row["summary"].startswith("Backtest · heikin_ashi · NIFTY · 2026-09-01 → 2026-09-11 · ")
    assert row["summary"].endswith("demo data")
    assert row["details"]["metrics"]["total_trades"] == res.json()["metrics"]["total_trades"]


def test_oauth_callback_never_logs_the_code_or_state(client, store):
    r = client.get("/auth/callback", params={"code": "SUPERSECRETCODE123", "state": "forged-state-xyz"}, follow_redirects=False)
    assert r.status_code == 302
    rows = stored(store, category="auth")
    assert len(rows) == 1 and rows[0]["level"] == "WARN" and rows[0]["action"] == "login_failed"
    blob = json.dumps(stored(store))
    assert "SUPERSECRETCODE123" not in blob and "forged-state-xyz" not in blob


def test_report_loads_are_logged(client, store):
    assert client.get("/trades", params={"from": "2026-10-01", "to": "2026-10-14"}).status_code == 200
    (row,) = stored(store, category="reports")
    assert row["action"] == "trades_query" and row["summary"] == "Loaded trades 2026-10-01 → 2026-10-14 · 0 rows"
