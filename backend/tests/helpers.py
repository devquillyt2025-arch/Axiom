"""Synthetic fixtures shared by engine and bot tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd

from bot.strategy import Context, OpenPosition, Signal, Strategy
from core.timeutil import IST, MARKET_OPEN


def day_bars(d: date, price_at: Callable[[int], float], tf: int = 5, wick: float = 0.0) -> pd.DataFrame:
    """Bars for one session. `price_at(minute_offset)` gives the price at that many minutes after 09:15;
    each bar opens at price_at(start) and closes at price_at(start+tf)."""
    start = datetime.combine(d, MARKET_OPEN, tzinfo=IST)
    rows, idx = [], []
    for k in range(375 // tf):
        m = k * tf
        o, c = price_at(m), price_at(m + tf)
        rows.append((o, max(o, c) + wick, min(o, c) - wick, c, 1000.0, 0.0))
        idx.append(start + timedelta(minutes=m))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume", "oi"], index=pd.DatetimeIndex(idx, name="ts"))


def flat(price: float = 24500.0) -> Callable[[int], float]:
    return lambda m: price


def ramp(start: float, per_min: float, from_min: int = 0) -> Callable[[int], float]:
    return lambda m: start + per_min * max(0, m - from_min)


class Scripted(Strategy):
    """Fires `direction` on the bar that starts at `enter_bar_minute` after the open (then every
    later bar too if `repeat`). Never exits on its own."""

    key = "scripted"
    name = "Scripted"
    warmup_bars = 0

    def __init__(self, direction="BULLISH", enter_bar_minute=30, repeat=False, **overrides):
        super().__init__(**overrides)
        self.direction, self.enter_bar_minute, self.repeat = direction, enter_bar_minute, repeat

    def min_bars(self) -> int:
        return 0

    def should_enter(self, ctx: Context) -> Signal | None:
        minute = int((ctx.bar_start - ctx.bar_start.replace(hour=9, minute=15)).total_seconds() // 60)
        if minute == self.enter_bar_minute or (self.repeat and minute > self.enter_bar_minute):
            return Signal(self.direction, "scripted")
        return None

    def should_exit(self, ctx: Context, pos: OpenPosition) -> str | None:
        return None


def vix_series(d: date, value: float = 14.0) -> pd.Series:
    days = [d - timedelta(days=i) for i in range(10, 0, -1)]
    return pd.Series([value] * len(days), index=pd.Index(days, name="date"))
