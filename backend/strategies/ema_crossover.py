from __future__ import annotations

import pandas as pd

from bot.strategy import Context, OpenPosition, Param, Signal, Strategy
from core.indicators import crossed_above, crossed_below, ema
from strategies.registry import register


@register
class EmaCrossover(Strategy):
    key = "ema_crossover"
    name = "EMA Crossover"
    description = (
        "Trend following. A fast EMA crossing above the slow EMA is a bullish signal, below is bearish. "
        "Closes the position on the opposite cross."
    )
    params = (
        Param("fast", "Fast EMA", 9, "int", 2, 100, 1),
        Param("slow", "Slow EMA", 21, "int", 3, 300, 1),
    )

    def __init__(self, **overrides):
        super().__init__(**overrides)
        if self.p["fast"] >= self.p["slow"]:
            raise ValueError("fast EMA must be shorter than slow EMA")

    def min_bars(self) -> int:
        return self.p["slow"] * 3  # let the slow EMA settle

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        fast, slow = ema(df["close"], self.p["fast"]), ema(df["close"], self.p["slow"])
        df["ema_fast"], df["ema_slow"] = fast, slow
        df["cross_up"], df["cross_dn"] = crossed_above(fast, slow), crossed_below(fast, slow)
        return df

    def should_enter(self, ctx: Context) -> Signal | None:
        if ctx.i < self.min_bars():
            return None
        f, s = self.p["fast"], self.p["slow"]
        if ctx.bar["cross_up"]:
            return Signal("BULLISH", f"EMA{f} crossed above EMA{s}")
        if ctx.bar["cross_dn"]:
            return Signal("BEARISH", f"EMA{f} crossed below EMA{s}")
        return None

    def should_exit(self, ctx: Context, pos: OpenPosition) -> str | None:
        if pos.direction == "BULLISH" and ctx.bar["cross_dn"]:
            return "EMA bearish cross"
        if pos.direction == "BEARISH" and ctx.bar["cross_up"]:
            return "EMA bullish cross"
        return None
