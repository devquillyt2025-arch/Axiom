from __future__ import annotations

import numpy as np
import pandas as pd

from bot.strategy import Context, OpenPosition, Param, Signal, Strategy
from core.timeutil import MARKET_OPEN
from strategies.registry import register


@register
class OpeningRangeBreakout(Strategy):
    key = "orb_breakout"
    name = "Opening Range Breakout"
    description = (
        "Marks the high/low of the first N minutes. The first candle to close beyond that range sets "
        "the day's direction (one trade per day). Exits if price closes back inside the range."
    )
    params = (
        Param("or_minutes", "Opening range (min)", 15, "select", options=(15, 30, 45, 60)),
        Param("buffer_pct", "Breakout buffer (%)", 0.05, "float", 0, 1, 0.05,
              help="Close must clear the range by this % to count."),
    )

    def min_bars(self) -> int:
        return 1

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if df.empty:
            for c in ("or_high", "or_low", "orb_up", "orb_dn"):
                df[c] = []
            return df
        day = pd.Index(df.index.date, name="day")
        open_ts = pd.Series(
            [pd.Timestamp.combine(d, MARKET_OPEN).tz_localize(df.index.tz) for d in day], index=df.index
        )
        minutes_in = ((df.index.to_series() - open_ts).dt.total_seconds() // 60).astype(float)
        in_or = minutes_in < self.p["or_minutes"]
        # Range values are only *used* on bars that start after the range completes (after_or),
        # so no bar acts on information from its own future.
        df["or_high"] = df["high"].where(in_or).groupby(day).transform("max")
        df["or_low"] = df["low"].where(in_or).groupby(day).transform("min")
        after_or = ~in_or
        buf = self.p["buffer_pct"] / 100
        up = after_or & (df["close"] > df["or_high"] * (1 + buf))
        dn = after_or & (df["close"] < df["or_low"] * (1 - buf))
        any_break = (up | dn).astype(int)
        first = any_break.groupby(day).cumsum() == 1
        df["orb_up"] = (up & first).astype(bool)
        df["orb_dn"] = (dn & first).astype(bool)
        return df

    def should_enter(self, ctx: Context) -> Signal | None:
        b = ctx.bar
        if b["orb_up"]:
            return Signal("BULLISH", f"Closed above {self.p['or_minutes']}m range high {b['or_high']:.1f}")
        if b["orb_dn"]:
            return Signal("BEARISH", f"Closed below {self.p['or_minutes']}m range low {b['or_low']:.1f}")
        return None

    def should_exit(self, ctx: Context, pos: OpenPosition) -> str | None:
        b = ctx.bar
        if np.isnan(b["or_high"]):
            return None
        if pos.direction == "BULLISH" and b["close"] < b["or_high"]:
            return "Back inside opening range"
        if pos.direction == "BEARISH" and b["close"] > b["or_low"]:
            return "Back inside opening range"
        return None
