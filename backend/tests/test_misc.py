from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from bot.contracts import Contract
from bot.executor import Executor, round_to_tick
from bot.logger import BotLogger
from bot.risk import RiskManager
from core import indicators as ind
from core.config import Settings
from core.mood import market_mood
from core.store import SqliteStore, StoreError
from core.timeutil import IST, next_token_expiry
from core.upstox import UpstoxError, candles_to_df

C = Contract("NSE_FO|1", "NIFTY 24500 PE 20 OCT 26", "PE", 24500.0, "2026-10-20", 65, 0.05, 1800)


# ------------------------------------------------------------------ store
def test_sqlite_store_filters_bools_json_and_paging(tmp_path):
    s = SqliteStore(tmp_path / "x.db")
    for i in range(5):
        s.insert("trades", {"instrument": "NIFTY 1 PE", "action": "SELL", "quantity": 65, "price": 10 + i, "status": "complete",
                            "pnl": None if i % 2 == 0 else float(i), "is_paper": i < 3, "meta": {"reason": f"r{i}"}})
    assert len(s.select("trades")) == 5
    paper = s.select("trades", [("is_paper", "eq", True)])
    assert len(paper) == 3 and all(r["is_paper"] is True for r in paper)
    assert s.select("trades", [("price", "gte", 12)], order="price", desc=False)[0]["price"] == 12
    assert s.select("trades", limit=1)[0]["meta"]["reason"].startswith("r")
    assert len(s.select_all("trades")) == 5
    with pytest.raises(StoreError):
        s.select("trades", [("nope; DROP TABLE trades", "eq", 1)])
    with pytest.raises(StoreError):
        s.select("users")


# ------------------------------------------------------------------ risk
def test_risk_daily_loss_and_drawdown_and_caps():
    r = RiskManager(max_daily_loss=1000, max_open_positions=1, max_lots=2)
    r.update_mtm(500)
    r.update_mtm(-200)
    assert r.max_drawdown == 700 and not r.halted
    assert r.can_enter(0)[0] and not r.can_enter(1)[0]
    r.record_realized(-800)  # realised -800, unrealised -200 => -1000 => at the limit
    assert r.halted and not r.can_enter(0)[0]
    assert r.clamp_lots(10) == 2 and r.clamp_lots(0) == 1


# ------------------------------------------------------------------ auth / time
def test_token_expiry_is_next_0330_ist():
    assert next_token_expiry(datetime(2026, 10, 14, 20, 0, tzinfo=IST)) == datetime(2026, 10, 15, 3, 30, tzinfo=IST)
    assert next_token_expiry(datetime(2026, 10, 14, 2, 0, tzinfo=IST)) == datetime(2026, 10, 14, 3, 30, tzinfo=IST)


# ------------------------------------------------------------------ indicators / mood / candles
def test_rsi_extremes_and_ema_seed():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up, 14).iloc[-1] == 100.0
    assert ind.rsi(-up, 14).iloc[-1] < 1e-9
    assert ind.ema(pd.Series([10.0, 10, 10]), 3).iloc[-1] == 10


def test_mood_rules():
    assert market_mood(1.3, 14)["label"] == "Bullish"
    assert market_mood(0.6, 14)["label"] == "Bearish"
    assert market_mood(0.95, 14)["label"] == "Neutral"
    assert market_mood(1.05, 25)["label"] == "Neutral"  # fear discounts a mildly bullish PCR
    assert market_mood(None, None)["label"] == "Neutral"


def test_candles_parse_is_ascending_ist_even_if_api_is_newest_first():
    raw = [["2026-10-14T09:20:00+05:30", 2, 3, 1, 2.5, 10, 0], ["2026-10-14T09:15:00+05:30", 1, 2, 0.5, 1.5, 5, 0]]
    df = candles_to_df(raw)
    assert list(df["open"]) == [1, 2] and str(df.index[0].tzinfo) == "IST"


# ------------------------------------------------------------------ executor
def test_round_to_tick():
    assert round_to_tick(100.02, 0.05, "up") == 100.05
    assert round_to_tick(100.07, 0.05, "down") == 100.05
    assert round_to_tick(0.01, 0.05, "down") == 0.05


def _executor(paper, client=None, **kw):
    s = Settings(_env_file=None, order_fill_timeout_s=3, **kw)
    return Executor(client, paper, BotLogger(SqliteStore(Path(tempfile.mkdtemp()) / "e.db")), s)


def test_paper_fill_applies_slippage_in_the_unfavourable_direction():
    ex = _executor(True, paper_slippage_points=0.5)
    sell = ex.execute(C, "SELL", 65, 100.0, "t")
    buy = ex.execute(C, "BUY", 65, 100.0, "t")
    assert sell.avg_price == 99.5 and buy.avg_price == 100.5 and sell.status == "complete"
    assert sell.order_ids[0].startswith("PAPER-")


class LiveFake:
    def __init__(self, behaviour):
        self.behaviour, self.bodies, self.cancelled, self.polls = behaviour, [], [], 0

    def place_order(self, body, algo=""):
        self.bodies.append(body)
        if self.behaviour == "reject":
            raise UpstoxError(400, "UDAPI1", "margin shortfall")
        if self.behaviour == "network":
            raise httpx.ConnectTimeout("boom")
        return ["OID1"]

    def orders(self):
        self.polls += 1
        tag = self.bodies[-1]["tag"]
        if self.behaviour == "fill":
            return [{"order_id": "OID1", "tag": tag, "status": "complete", "filled_quantity": 65, "average_price": 99.9}]
        if self.behaviour == "partial_then_stuck":
            st = "cancelled" if self.cancelled else "open"
            return [{"order_id": "OID1", "tag": tag, "status": st, "filled_quantity": 30, "average_price": 99.0}]
        if self.behaviour == "network":  # the order DID reach the exchange
            return [{"order_id": "OID9", "tag": tag, "status": "complete", "filled_quantity": 65, "average_price": 100.0}]
        return []

    def cancel_order(self, oid, algo=""):
        self.cancelled.append(oid)
        return oid


def test_live_order_body_matches_upstox_v3_contract_and_fill_is_read_back():
    fake = LiveFake("fill")
    fill = _executor(False, fake, order_price_buffer_pct=1.0).execute(C, "SELL", 65, 100.0, "AD-test")
    b = fake.bodies[0]
    assert b["order_type"] == "LIMIT", "market orders are no longer accepted by Upstox"
    assert b["price"] == 99.0 and b["transaction_type"] == "SELL" and b["product"] == "I" and b["validity"] == "DAY"
    assert b["instrument_token"] == "NSE_FO|1" and b["quantity"] == 65 and b["tag"] == "AD-test" and b["slice"] is False
    assert fill.status == "complete" and fill.filled_qty == 65 and fill.avg_price == 99.9


def test_live_buy_limit_is_rounded_up_and_big_orders_are_sliced():
    fake = LiveFake("fill")
    c = Contract("NSE_FO|1", "X", "PE", 1.0, "2026-10-20", 65, 0.05, 130)
    _executor(False, fake, order_price_buffer_pct=1.0).execute(c, "BUY", 260, 100.03, "t")
    assert fake.bodies[0]["price"] == 101.05 and fake.bodies[0]["slice"] is True


def test_live_rejection_and_unfilled_timeout_cancel_and_partial():
    assert _executor(False, LiveFake("reject")).execute(C, "SELL", 65, 100.0, "t").status == "rejected"

    fake = LiveFake("partial_then_stuck")
    f = _executor(False, fake).execute(C, "SELL", 65, 100.0, "t")
    assert fake.cancelled == ["OID1"], "unfilled remainder must be cancelled after the timeout"
    assert f.status == "partial" and f.filled_qty == 30


def test_network_error_during_placement_reconciles_by_tag_instead_of_retrying():
    fake = LiveFake("network")
    f = _executor(False, fake).execute(C, "SELL", 65, 100.0, "AD-net")
    assert len(fake.bodies) == 1, "placement must never be retried automatically"
    assert f.status == "complete" and f.filled_qty == 65
