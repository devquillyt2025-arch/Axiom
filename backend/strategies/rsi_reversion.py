from __future__ import annotations

import pandas as pd

from bot.strategy import Context, OpenPosition, Param, Signal, Strategy
from core.indicators import rsi
from strategies.registry import register


@register
class RsiReversion(Strategy):
    key = "rsi_reversion"
    name = "RSI Mean Reversion"
    description = (
        "Fades extremes. When RSI turns back up through the oversold level the setup is bullish; "
        "when it turns back down through overbought it is bearish. Exits once RSI returns to the midline."
    )
    params = (
        Param("period", "RSI period", 14, "int", 2, 50, 1),
        Param("oversold", "Oversold level", 30, "float", 5, 45, 1),
        Param("overbought", "Overbought level", 70, "float", 55, 95, 1),
        Param("exit_level", "Exit at RSI", 50, "float", 40, 60, 1),
    )

    def __init__(self, **overrides):
        super().__init__(**overrides)
        if not self.p["oversold"] < self.p["exit_level"] < self.p["overbought"]:
            raise ValueError("need oversold < exit level < overbought")

    def min_bars(self) -> int:
        return self.p["period"] * 3

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["close"], self.p["period"])
        return df

    def should_enter(self, ctx: Context) -> Signal | None:
        prev = ctx.prev
        if prev is None or ctx.i < self.min_bars() or pd.isna(prev["rsi"]) or pd.isna(ctx.bar["rsi"]):
            return None
        now, before = ctx.bar["rsi"], prev["rsi"]
        if before < self.p["oversold"] <= now:
            return Signal("BULLISH", f"RSI {before:.0f}→{now:.0f} turned up from oversold")
        if before > self.p["overbought"] >= now:
            return Signal("BEARISH", f"RSI {before:.0f}→{now:.0f} turned down from overbought")
        return None

    def should_exit(self, ctx: Context, pos: OpenPosition) -> str | None:
        r = ctx.bar["rsi"]
        if pd.isna(r):
            return None
        if pos.direction == "BULLISH" and r >= self.p["exit_level"]:
            return f"RSI back at {r:.0f}"
        if pos.direction == "BEARISH" and r <= self.p["exit_level"]:
            return f"RSI back at {r:.0f}"
        return None
