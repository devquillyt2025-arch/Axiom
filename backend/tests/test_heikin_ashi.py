"""Heikin Ashi indicator + colour-coded strategy: math, causality, session restart, signals, and a real backtest."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from backtest.engine import BacktestConfig, run_backtest
from bot.strategy import Context, OpenPosition
from core.indicators import heikin_ashi
from core.timeutil import IST
from strategies import REGISTRY, get_strategy
from tests.helpers import day_bars, vix_series

D = date(2026, 9, 14)  # a Monday
OHLC = ["open", "high", "low", "close"]


def v_path(slope: float):
    """Sell-off to minute 60, rally to minute 180, sell-off again, at `slope` index points per minute."""
    def price_at(m: int) -> float:
        if m <= 60:
            return 24500 - slope * m
        if m <= 180:
            return 24500 - slope * 60 + slope * (m - 60)
        return 24500 - slope * 60 + slope * 120 - slope * (m - 180)
    return price_at


v_shape = v_path(3.0)


def bars(price_at=v_shape, d: date = D, wick: float = 2.0) -> pd.DataFrame:
    return day_bars(d, price_at, wick=wick)


def signals(strategy, raw: pd.DataFrame) -> list[tuple[int, str]]:
    df = strategy.prepare(raw)
    out = []
    for i in range(len(df)):
        s = strategy.should_enter(Context(df=df, i=i, spot=float(df["close"].iloc[i]), vix=14.0, underlying="NIFTY", timeframe_minutes=5))
        if s:
            out.append((i, s.direction))
    return out


# ------------------------------------------------------------------ indicator
def test_heikin_ashi_matches_hand_computed_values():
    idx = pd.DatetimeIndex([datetime(2026, 9, 14, 9, 15 + 5 * k, tzinfo=IST) for k in range(3)])
    raw = pd.DataFrame({"open": [100, 105, 108], "high": [110, 112, 109], "low": [95, 100, 90], "close": [105, 108, 92]}, index=idx, dtype=float)
    ha = heikin_ashi(raw)
    assert ha["ha_close"].tolist() == pytest.approx([102.5, 106.25, 99.75])
    assert ha["ha_open"].tolist() == pytest.approx([102.5, 102.5, 104.375])  # seed (o+c)/2, then avg of previous ha open/close
    assert ha["ha_high"].tolist() == pytest.approx([110, 112, 109])
    assert ha["ha_low"].tolist() == pytest.approx([95, 100, 90])


def test_heikin_ashi_is_causal_and_restarts_each_session():
    two_days = pd.concat([bars(d=D), bars(price_at=lambda m: 24400 + 2.0 * m, d=D + timedelta(days=1))])
    full = heikin_ashi(two_days)
    for k in (1, 7, 40, 75, 76, 100, 150):  # no lookahead: a prefix gives the same values as the whole series
        assert_frame_equal(heikin_ashi(two_days.iloc[:k]), full.iloc[:k])
    day2 = two_days[two_days.index.date == D + timedelta(days=1)]
    assert_frame_equal(heikin_ashi(day2), full.loc[day2.index])  # day 2 is independent of how much history precedes it


def test_prepare_never_touches_real_prices():
    raw = bars()
    prepared = get_strategy("heikin_ashi").prepare(raw)
    assert_frame_equal(prepared[OHLC], raw[OHLC])
    assert {"ha_open", "ha_high", "ha_low", "ha_close", "ha_color", "ha_run", "ha_flipped"} <= set(prepared.columns)


# ------------------------------------------------------------------ colour logic
def test_colour_follows_the_trend_and_first_colour_is_not_a_flip():
    df = get_strategy("heikin_ashi").prepare(bars())
    assert df["ha_color"].iloc[0] == 0  # symmetric first candle is a doji: no colour yet
    assert df["ha_color"].iloc[1] == -1 and not df["ha_flipped"].iloc[1]  # first colour of the day, not a change
    assert df["ha_color"].iloc[10] == -1 and df["ha_run"].iloc[10] == 10  # sell-off: a long red run
    assert df["ha_color"].iloc[28] == 1 and df["ha_flipped"].iloc[28]  # bar 28 = minute 140, mid-rally: green


def test_signals_fire_once_on_each_colour_change():
    s = get_strategy("heikin_ashi")
    sig = signals(s, bars())
    assert [d for _, d in sig] == ["BULLISH", "BEARISH"]
    (up_i, _), (dn_i, _) = sig
    df = s.prepare(bars())
    assert df["ha_color"].iloc[up_i] == 1 and df["ha_color"].iloc[up_i - 1] == -1
    assert df["ha_color"].iloc[dn_i] == -1 and df["ha_color"].iloc[dn_i - 1] == 1
    assert 12 <= up_i <= 20  # the real low is at bar 12 (minute 60); smoothing makes it lag, but not by much
    assert 36 <= dn_i <= 44  # the real high is at bar 36 (minute 180)


def test_confirm_candles_waits_for_more_candles_of_the_new_colour():
    (i1, _), (j1, _) = signals(get_strategy("heikin_ashi"), bars())
    (i2, _), (j2, _) = signals(get_strategy("heikin_ashi", confirm_candles=2), bars())
    assert (i2, j2) == (i1 + 1, j1 + 1)
    (i3, _), _ = signals(get_strategy("heikin_ashi", confirm_candles=3), bars())
    assert i3 == i1 + 2


def test_strong_candles_filter_can_only_remove_signals():
    plain = signals(get_strategy("heikin_ashi"), bars())
    strong_s = get_strategy("heikin_ashi", require_no_wick="Yes")
    strong = signals(strong_s, bars())
    assert set(strong) <= set(plain)
    df = strong_s.prepare(bars())
    for i, direction in strong:  # every surviving signal really is a no-wick candle
        r = df.iloc[i]
        assert (r["ha_low"] >= r["ha_open"]) if direction == "BULLISH" else (r["ha_high"] <= r["ha_open"])


def test_flat_market_gives_no_signals():
    assert signals(get_strategy("heikin_ashi"), bars(price_at=lambda m: 24500.0)) == []


def test_a_new_session_does_not_inherit_yesterdays_colour():
    two = pd.concat([bars(price_at=lambda m: 24500 + 3.0 * m), bars(price_at=lambda m: 24600 - 3.0 * m, d=D + timedelta(days=1))])
    df = get_strategy("heikin_ashi").prepare(two)
    first_of_day2 = list(two.index.date).index(D + timedelta(days=1))
    assert df["ha_color"].iloc[first_of_day2 - 1] == 1  # yesterday ended green
    assert not df["ha_flipped"].iloc[first_of_day2:first_of_day2 + 2].any()  # today's first colour (red) is not a flip
    assert [d for _, d in signals(get_strategy("heikin_ashi"), two)] == []


def test_exit_on_first_opposite_colour():
    s = get_strategy("heikin_ashi")
    df = s.prepare(bars())
    ctx = lambda i: Context(df=df, i=i, spot=24500.0, vix=14.0, underlying="NIFTY", timeframe_minutes=5)  # noqa: E731

    def pos(direction: str) -> OpenPosition:
        return OpenPosition("p", "heikin_ashi", "NIFTY", "", "X", "PE", 24500, "2026-09-17", "SELL", 75, 75, 100.0,
                            datetime(2026, 9, 14, 10, 0, tzinfo=IST), 100.0, direction)

    assert s.should_exit(ctx(5), pos("BULLISH")) == "Heikin Ashi turned red"  # red candle while long
    assert s.should_exit(ctx(5), pos("BEARISH")) is None
    assert s.should_exit(ctx(30), pos("BEARISH")) == "Heikin Ashi turned green"  # green candle while short
    assert s.should_exit(ctx(30), pos("BULLISH")) is None


def test_parameter_validation_and_registration():
    assert "heikin_ashi" in REGISTRY
    with pytest.raises(ValueError):
        get_strategy("heikin_ashi", confirm_candles=0)
    with pytest.raises(ValueError):
        get_strategy("heikin_ashi", require_no_wick="Maybe")
    names = {p["key"] for p in REGISTRY["heikin_ashi"].describe()["params"]}
    assert {"confirm_candles", "require_no_wick", "timeframe_minutes", "option_side"} <= names


# ------------------------------------------------------------------ through the real engine
def test_full_backtest_trades_the_colour_changes_at_real_prices():
    cfg = BacktestConfig(strategy="heikin_ashi", symbol="NIFTY", start=D, end=D, params={}, slippage=0.0, charges_per_order=0.0)
    s = get_strategy("heikin_ashi", sl_pct=100.0, target_pct=95.0)  # keep premium stops out of the way; colour drives exits
    raw = bars(price_at=v_path(0.5))  # gentle enough that the sold option keeps most of its premium until the colour flips
    r = run_backtest(cfg, raw, vix_series(D), s)
    t = r["trades"]
    assert len(t) == 2, [(x["signal_reason"], x["exit_reason"]) for x in t]
    long_leg, short_leg = t  # BULLISH + SELL => sell PE; then BEARISH + SELL => sell CE
    assert "PE" in long_leg["instrument"] and long_leg["signal_reason"] == "Heikin Ashi turned green"
    assert long_leg["exit_reason"] == "Heikin Ashi turned red"  # the bearish flip closes the long and reverses
    assert "CE" in short_leg["instrument"] and short_leg["signal_reason"] == "Heikin Ashi turned red"
    assert short_leg["exit_reason"] == "Square-off"  # no further colour change, so the platform flattens at 15:15
    # no lookahead: the entry fills on the bar AFTER the signal candle closed
    sig_i = signals(s, raw)[0][0]
    assert long_leg["entry_time"].startswith((raw.index[sig_i] + timedelta(minutes=5)).strftime("2026-09-14T%H:%M"))
