from __future__ import annotations

import numpy as np
import pandas as pd

from bot.strategy import Context, OpenPosition, Param, Signal, Strategy
from core.indicators import heikin_ashi
from strategies.registry import register


@register
class HeikinAshiTrend(Strategy):
    key = "heikin_ashi"
    name = "Heikin Ashi Trend"
    description = (
        "Colour-coded trend following on Heikin Ashi candles. A green candle right after a red one is bullish, "
        "a red one right after a green one is bearish, and the position closes on the first candle of the "
        "opposite colour. Signals read the smoothed candles; fills, stops and targets use real prices."
    )
    params = (
        Param("confirm_candles", "Candles of the new colour to confirm", 1, "int", 1, 5, 1,
              help="1 = act on the colour-change candle itself. 2+ waits until that many candles in a row have the new colour."),
        Param("require_no_wick", "Strong candles only", "No", "select", options=("No", "Yes"),
              help="Yes = the signal candle must be a clean momentum candle: a green one with no lower wick, a red one with no upper wick."),
    )
    warmup_bars = 3  # Heikin Ashi restarts every session, so there is no long indicator to warm up

    def min_bars(self) -> int:
        return self.p["confirm_candles"] + 1

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adds ha_* candles plus, per session: ha_color (+1 green / -1 red / 0 not yet known), ha_run (candles in
        a row of that colour) and ha_flipped (the run began after the opposite colour, so it is a real colour
        change and not just the session's first colour). The real open/high/low/close are left untouched."""
        df = df.copy()
        ha = heikin_ashi(df)
        for col in ha.columns:
            df[col] = ha[col]

        n = len(df)
        body = (df["ha_close"] - df["ha_open"]).to_numpy()
        days = df.index.date
        color = np.zeros(n, dtype=int)
        run = np.zeros(n, dtype=int)
        flipped = np.zeros(n, dtype=bool)
        for i in range(n):
            fresh = i == 0 or days[i] != days[i - 1]
            prev_color, prev_run, prev_flipped = (0, 0, False) if fresh else (color[i - 1], run[i - 1], flipped[i - 1])
            now = int(np.sign(body[i])) or prev_color  # a doji (open == close) keeps the running colour
            if now == 0:  # a doji as the very first candle of the session: no colour yet
                continue
            if now == prev_color:
                color[i], run[i], flipped[i] = now, prev_run + 1, prev_flipped
            else:
                color[i], run[i], flipped[i] = now, 1, prev_color != 0
        df["ha_color"], df["ha_run"], df["ha_flipped"] = color, run, flipped
        return df

    def should_enter(self, ctx: Context) -> Signal | None:
        if ctx.i < self.min_bars():
            return None
        b, need = ctx.bar, self.p["confirm_candles"]
        if not b["ha_flipped"] or b["ha_run"] != need:
            return None
        strong = self.p["require_no_wick"] == "Yes"
        after = f" ({need} candles)" if need > 1 else ""
        if b["ha_color"] > 0 and (not strong or b["ha_low"] >= b["ha_open"]):
            return Signal("BULLISH", f"Heikin Ashi turned green{after}")
        if b["ha_color"] < 0 and (not strong or b["ha_high"] <= b["ha_open"]):
            return Signal("BEARISH", f"Heikin Ashi turned red{after}")
        return None

    def should_exit(self, ctx: Context, pos: OpenPosition) -> str | None:
        color = ctx.bar["ha_color"]
        if pos.direction == "BULLISH" and color < 0:
            return "Heikin Ashi turned red"
        if pos.direction == "BEARISH" and color > 0:
            return "Heikin Ashi turned green"
        return None
