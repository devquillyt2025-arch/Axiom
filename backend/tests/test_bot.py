"""End-to-end bot loop against a fake exchange + fake clock (paper mode, no network)."""
from __future__ import annotations

from datetime import date, datetime, time

import pytest

from bot import state as st
from bot.run import Bot
from core.config import Settings
from core.store import SqliteStore
from core.timeutil import IST
from strategies.registry import REGISTRY
from tests.helpers import Scripted, day_bars, flat

TODAY = date(2026, 10, 14)  # Wednesday


class FakeClient:
    """Just enough of UpstoxClient for the bot. `prices` is mutated by the tests."""

    def __init__(self):
        self.prices: dict[str, float] = {"NSE_INDEX|Nifty 50": 24500.0, "NSE_INDEX|India VIX": 14.0}
        self.placed: list[dict] = []

    def ltp(self, keys):
        return {k: self.prices[k] for k in keys if k in self.prices}

    def market_status(self, exchange):
        return "NORMAL_OPEN"

    def option_contracts(self, key, expiry=None):
        out = []
        for strike in range(24300, 24750, 50):
            for t in ("CE", "PE"):
                out.append({
                    "instrument_key": f"NSE_FO|{strike}{t}", "trading_symbol": f"NIFTY {strike} {t} 20 OCT 26",
                    "instrument_type": t, "strike_price": float(strike), "expiry": "2026-10-20",
                    "lot_size": 65, "tick_size": 0.05, "freeze_quantity": 1800,
                })
        return out

    def orders(self):
        return []

    def place_order(self, *a, **k):  # paper mode must never reach here
        self.placed.append({"a": a, "k": k})
        raise AssertionError("paper mode attempted a live order")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "bot_state.json")
    monkeypatch.setattr(st, "STOP_FILE", tmp_path / "bot.stop")
    monkeypatch.setitem(REGISTRY, "scripted", Scripted)
    store = SqliteStore(tmp_path / "t.db")
    client = FakeClient()
    clock = {"now": datetime.combine(TODAY, time(10, 0, 10), tzinfo=IST)}
    bars = day_bars(TODAY, flat(24500.0))

    def make(max_daily_loss=5000.0, **kw):
        s = Settings(_env_file=None, paper_trade=True, max_daily_loss=max_daily_loss, paper_slippage_points=0.5)
        bot = Bot(
            strategy_key="scripted", symbol="NIFTY", lots=1, paper=True, settings=s, store=store, client=client,
            candles_fn=lambda sym, tf, days: bars, clock=lambda: clock["now"], use_feed=False, **kw,
        )
        bot.strategy.direction, bot.strategy.enter_bar_minute = "BULLISH", 40  # signal on the 09:55 bar
        return bot

    def tick(bot, hh, mm, ss=10):
        clock["now"] = datetime.combine(TODAY, time(hh, mm, ss), tzinfo=IST)
        bot._last_fetch_try = 0.0  # the real-time retry throttle is irrelevant to a simulated clock
        return bot.tick()

    return type("Env", (), {"store": store, "client": client, "make": staticmethod(make), "tick": staticmethod(tick), "clock": clock})


def trades(env, bot):
    bot.log.close()  # flush the async writer
    return env.store.select("trades", order="created_at", desc=False)


def test_entry_then_stop_loss_then_risk_halt(env):
    bot = env.make(max_daily_loss=2000.0)
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    assert env.tick(bot, 10, 0)  # 10:00:10 -> closed 09:55 bar fires the signal
    assert len(bot.positions) == 1
    p = bot.positions[0]
    assert p.side == "SELL" and p.option_type == "PE" and p.qty == 65
    assert p.entry_price == pytest.approx(99.5)  # sold 0.5 under ltp (paper slippage)
    assert p.sl_price == pytest.approx(99.5 * 1.3) and p.target_price == pytest.approx(99.5 * 0.5)

    env.client.prices["NSE_FO|24500PE"] = 140.0  # premium blows through the 129.35 stop
    env.tick(bot, 10, 1)
    assert bot.positions == []
    assert bot.risk.realized == pytest.approx((99.5 - 140.5) * 65)  # bought back 0.5 over ltp
    assert bot.risk.halted, "a ~₹2.7k loss must breach the ₹2k daily limit"

    env.tick(bot, 10, 10)  # a later bar -> a fresh signal must be refused
    assert bot.positions == []

    rows = trades(env, bot)
    assert [r["action"] for r in rows] == ["SELL", "BUY"]
    assert rows[0]["pnl"] is None and rows[1]["pnl"] == pytest.approx(-2665.0)
    assert all(r["is_paper"] for r in rows)
    assert env.client.placed == []


def test_target_exit_and_pnl_sign(env):
    bot = env.make()
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    env.tick(bot, 10, 0)
    env.client.prices["NSE_FO|24500PE"] = 40.0  # decayed past the 49.75 target
    env.tick(bot, 10, 1)
    assert bot.positions == []
    assert bot.risk.realized == pytest.approx((99.5 - 40.5) * 65)
    assert not bot.risk.halted


def test_square_off_at_1515(env):
    bot = env.make()
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    env.tick(bot, 10, 0)
    assert len(bot.positions) == 1
    env.tick(bot, 15, 14, 59)
    assert len(bot.positions) == 1
    env.tick(bot, 15, 15, 1)
    assert bot.positions == []
    last = trades(env, bot)[-1]
    assert last["meta"]["reason"] == "Square-off"


def test_stop_request_flattens_and_stops(env):
    bot = env.make()
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    env.tick(bot, 10, 0)
    assert len(bot.positions) == 1
    st.request_stop()
    assert env.tick(bot, 10, 2) is False
    assert bot.positions == [] and bot.status == "stopped" and bot.finished
    assert not st.stop_requested(), "stop flag is cleared on exit"
    assert st.read_state()["status"] == "stopped"


def test_no_entries_outside_entry_window_and_weekend_exit(env):
    bot = env.make()
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    bot.strategy.enter_bar_minute = 355  # 15:10 bar -> after the 14:45 cutoff
    env.tick(bot, 15, 12)
    assert bot.positions == []

    bot2 = env.make()
    bot2.start()
    env.clock["now"] = datetime(2026, 10, 17, 11, 0, tzinfo=IST)  # Saturday
    assert bot2.tick() is False and bot2.status == "stopped"


def test_stale_candle_is_not_traded(env, monkeypatch):
    bot = env.make()
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    bot.candles_fn = lambda s, tf, d: day_bars(TODAY, flat())[:8]  # last bar starts 09:50; the 09:55 bar never arrives
    env.tick(bot, 10, 0, 50)  # >45 s into the bar and the closed candle still isn't there
    assert bot.positions == []
    assert any("never arrived" in r["message"] for r in bot.log.recent)


def test_restart_restores_todays_realised_pnl_and_halts(env):
    bot = env.make(max_daily_loss=2000.0)
    bot.start()
    env.client.prices["NSE_FO|24500PE"] = 100.0
    env.tick(bot, 10, 0)
    env.client.prices["NSE_FO|24500PE"] = 140.0
    env.tick(bot, 10, 1)
    trades(env, bot)  # flush

    reborn = env.make(max_daily_loss=2000.0)
    reborn.start()
    assert reborn.risk.realized == pytest.approx(-2665.0)
    assert reborn.risk.halted, "restarting must not reset the daily loss limit"
