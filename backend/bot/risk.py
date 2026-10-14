"""Pre-trade and running risk controls.

  * Daily loss limit: once realised + unrealised P&L for the day reaches -MAX_DAILY_LOSS the manager
    HALTS — no new entries for the rest of the day and the bot flattens what is open.
  * Max open positions: new entries are refused at the cap.
  * Max lots per order: a hard ceiling, regardless of what the UI or a strategy asks for.
  * Drawdown: peak-to-trough of the day's running P&L (realised + unrealised), for the stats bar.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskManager:
    max_daily_loss: float
    max_open_positions: int
    max_lots: int
    realized: float = 0.0
    unrealized: float = 0.0
    peak: float = 0.0
    max_drawdown: float = 0.0
    orders_fired: int = 0
    halted: bool = False
    halt_reason: str = ""

    @property
    def daily_pnl(self) -> float:
        return self.realized + self.unrealized

    def update_mtm(self, unrealized: float) -> None:
        self.unrealized = unrealized
        total = self.daily_pnl
        self.peak = max(self.peak, total)
        self.max_drawdown = max(self.max_drawdown, self.peak - total)
        if not self.halted and total <= -self.max_daily_loss:
            self.halted = True
            self.halt_reason = f"Daily loss limit hit: ₹{total:,.0f} ≤ -₹{self.max_daily_loss:,.0f}"

    def record_realized(self, pnl: float) -> None:
        self.realized += pnl
        self.update_mtm(self.unrealized)

    def record_order(self) -> None:
        self.orders_fired += 1

    def clamp_lots(self, lots: int) -> int:
        return max(1, min(int(lots), self.max_lots))

    def can_enter(self, open_positions: int) -> tuple[bool, str]:
        if self.halted:
            return False, self.halt_reason
        if open_positions >= self.max_open_positions:
            return False, f"At max open positions ({self.max_open_positions})"
        return True, ""

    def stats(self) -> dict:
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "realized": round(self.realized, 2),
            "unrealized": round(self.unrealized, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "orders_fired": self.orders_fired,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "max_daily_loss": self.max_daily_loss,
            "max_open_positions": self.max_open_positions,
            "max_lots": self.max_lots,
        }
