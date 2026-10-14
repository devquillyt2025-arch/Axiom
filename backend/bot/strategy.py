"""Base Strategy class + the shared position / stop / target logic.

A strategy looks at the *underlying index* (candles, VIX) and answers two questions:

    should_enter(ctx)        -> Signal | None        "go BULLISH / BEARISH now?"
    should_exit(ctx, pos)    -> str | None           "close this position? (reason)"

The platform — not the strategy — turns a Signal into an option leg and handles stops, targets,
time-based square-off, sizing and the daily-loss limit. The *same* Strategy object and the same
leg/level helpers below run in the live bot and in the backtester, so what you backtest is what
you trade (modulo the option-price model; see core/optionmodel.py).

Writing a strategy: drop a file in backend/strategies/, subclass Strategy, decorate with
@register. It shows up in the Backtest dropdown and in the bot's start dialog automatically.
`prepare()` must be CAUSAL (never look ahead, e.g. no shift(-1)) — the backtester calls it once
over the whole history, the live bot calls it on the history so far, and the two must agree.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar, Literal

import pandas as pd

Direction = Literal["BULLISH", "BEARISH"]
OptionSide = Literal["SELL", "BUY"]


# --------------------------------------------------------------------------- parameters
@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float | int | str
    kind: str = "float"  # int | float | select
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple = ()
    help: str = ""

    def coerce(self, value: Any) -> Any:
        if self.kind == "select":
            v = type(self.options[0])(value) if self.options else value
            if self.options and v not in self.options:
                raise ValueError(f"{self.key} must be one of {list(self.options)}")
            return v
        v = int(value) if self.kind == "int" else float(value)
        if self.min is not None and v < self.min:
            raise ValueError(f"{self.key} must be ≥ {self.min}")
        if self.max is not None and v > self.max:
            raise ValueError(f"{self.key} must be ≤ {self.max}")
        return v

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "default": self.default, "kind": self.kind,
            "min": self.min, "max": self.max, "step": self.step, "options": list(self.options), "help": self.help,
        }


COMMON_PARAMS: tuple[Param, ...] = (
    Param("timeframe_minutes", "Candle timeframe (min)", 5, "select", options=(1, 3, 5, 10, 15)),
    Param("option_side", "Option side", "SELL", "select", options=("SELL", "BUY"),
          help="SELL = collect premium (bullish→sell PE, bearish→sell CE). BUY = pay premium (bullish→buy CE, bearish→buy PE)."),
    Param("sl_pct", "Stop-loss (% of entry premium)", 30.0, "float", 5, 100, 5,
          help="SELL: exit if premium rises this much above entry. BUY: exit if it falls this much."),
    Param("target_pct", "Target (% of entry premium)", 50.0, "float", 5, 95, 5,
          help="SELL: exit when premium decays this much. BUY: exit when it gains this much."),
)


# --------------------------------------------------------------------------- data classes
@dataclass
class Signal:
    direction: Direction
    reason: str = ""
    sl_pct: float | None = None  # overrides the strategy's sl_pct for this trade
    target_pct: float | None = None


@dataclass
class Context:
    """Everything a strategy may look at. `df` holds CLOSED bars only (ascending), already run
    through `Strategy.prepare`; `i` is the index of the bar that just closed."""

    df: pd.DataFrame
    i: int
    spot: float
    vix: float | None
    underlying: str
    timeframe_minutes: int

    @property
    def bar(self) -> pd.Series:
        return self.df.iloc[self.i]

    @property
    def prev(self) -> pd.Series | None:
        return self.df.iloc[self.i - 1] if self.i > 0 else None

    @property
    def bar_start(self) -> datetime:
        return self.df.index[self.i].to_pydatetime()

    @property
    def closed_at(self) -> datetime:
        return self.bar_start + timedelta(minutes=self.timeframe_minutes)


@dataclass
class OpenPosition:
    id: str
    strategy: str
    underlying: str
    instrument_key: str
    trading_symbol: str
    option_type: str  # CE | PE
    strike: float
    expiry: str
    side: OptionSide
    qty: int  # units (lots × lot_size)
    lot_size: int
    entry_price: float
    entry_time: datetime
    last_price: float
    direction: Direction
    sl_price: float | None = None
    target_price: float | None = None
    reason: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def unrealised(self) -> float:
        diff = (self.entry_price - self.last_price) if self.side == "SELL" else (self.last_price - self.entry_price)
        return diff * self.qty

    def to_dict(self) -> dict:
        return {
            "id": self.id, "strategy": self.strategy, "underlying": self.underlying,
            "instrument": self.trading_symbol, "instrument_key": self.instrument_key,
            "option_type": self.option_type, "strike": self.strike, "expiry": self.expiry,
            "side": self.side, "qty": self.qty, "lot_size": self.lot_size,
            "avg_price": self.entry_price, "ltp": self.last_price, "pnl": round(self.unrealised, 2),
            "sl": self.sl_price, "target": self.target_price, "direction": self.direction,
            "entry_time": self.entry_time.isoformat(), "reason": self.reason,
        }


# --------------------------------------------------------------------------- shared helpers
def leg_for(direction: Direction, option_side: OptionSide) -> tuple[str, OptionSide]:
    """Signal direction -> (option type, side). The one place this mapping lives."""
    if option_side == "SELL":
        return ("PE", "SELL") if direction == "BULLISH" else ("CE", "SELL")
    return ("CE", "BUY") if direction == "BULLISH" else ("PE", "BUY")


def exit_levels(side: OptionSide, entry: float, sl_pct: float, target_pct: float) -> tuple[float, float]:
    """(stop price, target price) on the option premium."""
    if side == "SELL":
        return entry * (1 + sl_pct / 100), max(entry * (1 - target_pct / 100), 0.05)
    return max(entry * (1 - sl_pct / 100), 0.05), entry * (1 + target_pct / 100)


def stop_or_target_hit(pos: OpenPosition, price: float) -> str | None:
    """'SL' / 'TARGET' / None for a premium `price`. Stop wins if both could apply."""
    if pos.side == "SELL":
        if pos.sl_price is not None and price >= pos.sl_price:
            return "SL"
        if pos.target_price is not None and price <= pos.target_price:
            return "TARGET"
    else:
        if pos.sl_price is not None and price <= pos.sl_price:
            return "SL"
        if pos.target_price is not None and price >= pos.target_price:
            return "TARGET"
    return None


# --------------------------------------------------------------------------- base class
class Strategy(ABC):
    key: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    params: ClassVar[tuple[Param, ...]] = ()
    warmup_bars: ClassVar[int] = 60  # bars of history needed before signals are trusted

    def __init__(self, **overrides: Any):
        specs = {p.key: p for p in self.param_specs()}
        unknown = set(overrides) - set(specs)
        if unknown:
            raise ValueError(f"Unknown parameter(s) for {self.key}: {sorted(unknown)}")
        self.p: dict[str, Any] = {k: spec.coerce(overrides.get(k, spec.default)) for k, spec in specs.items()}

    @classmethod
    def param_specs(cls) -> list[Param]:
        return [*COMMON_PARAMS, *cls.params]

    @classmethod
    def describe(cls) -> dict:
        return {
            "key": cls.key, "name": cls.name, "description": cls.description,
            "warmup_bars": cls.warmup_bars, "params": [p.to_dict() for p in cls.param_specs()],
        }

    @property
    def timeframe_minutes(self) -> int:
        return int(self.p["timeframe_minutes"])

    @property
    def option_side(self) -> OptionSide:
        return self.p["option_side"]

    def min_bars(self) -> int:
        """Bars that must exist before `should_enter` is consulted (override if it depends on params)."""
        return self.warmup_bars

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add causal indicator columns. Must not look ahead."""
        return df

    @abstractmethod
    def should_enter(self, ctx: Context) -> Signal | None: ...

    def should_exit(self, ctx: Context, pos: OpenPosition) -> str | None:
        """Return a reason string to close `pos` at the next opportunity, else None.
        Stops, targets, square-off time and the daily-loss limit are handled by the platform."""
        return None
