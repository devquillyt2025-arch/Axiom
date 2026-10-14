"""Order placement / modification / cancellation via Upstox's v3 order API.

PAPER mode never touches the order API: fills are simulated at the reference price plus a
configured slippage. LIVE mode sends *marketable LIMIT* orders (Upstox no longer accepts plain
market orders over the API), then watches the order book and cancels whatever hasn't filled
within ORDER_FILL_TIMEOUT_S. Order-mutating calls are never auto-retried; if the network drops
mid-placement we reconcile against the order book by tag before deciding what happened.

NOTE: live paths were written against Upstox's documented API but could not be exercised
against a real account when this was built. Run in PAPER mode first, then trade 1 lot live
and watch the Upstox order book before scaling.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import httpx

from bot.auth import AuthRequired
from bot.contracts import Contract
from bot.logger import BotLogger
from core.config import Settings
from core.timeutil import now_ist
from core.upstox import UpstoxClient, UpstoxError


@dataclass
class Fill:
    status: str  # complete | partial | unfilled | rejected | error | unknown
    filled_qty: int
    avg_price: float
    order_ids: list[str] = field(default_factory=list)
    message: str = ""


def round_to_tick(price: float, tick: float, direction: str) -> float:
    """direction 'up' (BUY limits) or 'down' (SELL limits); never below one tick."""
    steps = price / tick
    steps = math.ceil(steps - 1e-9) if direction == "up" else math.floor(steps + 1e-9)
    return round(max(steps * tick, tick), 2)


def _is_terminal(status: str) -> bool:
    s = (status or "").lower()
    return s.startswith(("complete", "reject", "cancel"))


class Executor:
    def __init__(
        self, client: UpstoxClient | None, paper: bool, log: BotLogger, settings: Settings,
        on_wait: Callable[[], None] | None = None,
    ):
        self.client, self.paper, self.log, self.s = client, paper, log, settings
        self.on_wait = on_wait  # called while polling for fills so the caller can keep its heartbeat alive
        self._seq = 0

    # ------------------------------------------------------------------ public
    def execute(self, contract: Contract, side: str, qty: int, ref_price: float, tag: str) -> Fill:
        if qty <= 0:
            return Fill("error", 0, 0.0, [], "quantity must be positive")
        if self.paper:
            return self._paper_fill(contract, side, qty, ref_price)
        try:
            return self._live(contract, side, qty, ref_price, tag)
        except AuthRequired as e:
            return Fill("error", 0, 0.0, [], f"auth: {e}")

    def modify(self, order_id: str, price: float, trigger_price: float = 0.0, order_type: str = "LIMIT") -> str:
        if self.paper:
            self.log.info(f"[paper] modify {order_id} -> {price}")
            return order_id
        assert self.client
        return self.client.modify_order(
            {"order_id": order_id, "validity": "DAY", "price": price, "order_type": order_type, "trigger_price": trigger_price},
            self.s.upstox_algo_name,
        )

    def cancel(self, order_id: str) -> str:
        if self.paper:
            self.log.info(f"[paper] cancel {order_id}")
            return order_id
        assert self.client
        return self.client.cancel_order(order_id, self.s.upstox_algo_name)

    # ------------------------------------------------------------------ paper
    def _paper_fill(self, c: Contract, side: str, qty: int, ref: float) -> Fill:
        slip = self.s.paper_slippage_points
        px = round_to_tick(ref + slip, c.tick_size, "up") if side == "BUY" else round_to_tick(ref - slip, c.tick_size, "down")
        self._seq += 1
        oid = f"PAPER-{now_ist():%Y%m%d}-{self._seq:04d}"
        return Fill("complete", qty, px, [oid], "simulated fill")

    # ------------------------------------------------------------------ live
    def _live(self, c: Contract, side: str, qty: int, ref: float, tag: str) -> Fill:
        assert self.client
        buf = self.s.order_price_buffer_pct / 100
        limit = round_to_tick(ref * (1 + buf), c.tick_size, "up") if side == "BUY" else round_to_tick(ref * (1 - buf), c.tick_size, "down")
        body = {
            "quantity": int(qty), "product": "I", "validity": "DAY", "price": limit, "tag": tag[:40],
            "instrument_token": c.instrument_key, "order_type": "LIMIT", "transaction_type": side,
            "disclosed_quantity": 0, "trigger_price": 0, "is_amo": False,
            "slice": bool(c.freeze_qty and qty > c.freeze_qty),
        }
        self.log.info(f"[live] placing {side} {qty} {c.trading_symbol} LIMIT {limit} (ref {ref}) tag={tag}")
        try:
            ids = self.client.place_order(body, self.s.upstox_algo_name)
        except UpstoxError as e:
            return Fill("rejected", 0, 0.0, [], str(e))
        except httpx.TransportError as e:
            # We don't know whether the exchange received it. Look for our tag before deciding.
            self.log.warn(f"network error placing order ({e}); reconciling by tag {tag}")
            time.sleep(1.5)
            ids = [o["order_id"] for o in self._safe_orders() if o.get("tag") == tag]
            if not ids:
                return Fill("unknown", 0, 0.0, [], "network error and no order with our tag found — verify in the Upstox app")
        if not ids:
            return Fill("error", 0, 0.0, [], "Upstox accepted the request but returned no order id")
        return self._await_fill(ids, tag, qty)

    def _safe_orders(self) -> list[dict]:
        try:
            return self.client.orders()  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001
            self.log.warn(f"could not read order book: {e}")
            return []

    @staticmethod
    def _aggregate(orders: list[dict]) -> tuple[int, float]:
        filled = sum(int(o.get("filled_quantity") or 0) for o in orders)
        notional = sum(float(o.get("average_price") or 0) * int(o.get("filled_quantity") or 0) for o in orders)
        return filled, (notional / filled if filled else 0.0)

    def _mine(self, ids: list[str], tag: str) -> list[dict]:
        return [o for o in self._safe_orders() if o.get("order_id") in ids or o.get("tag") == tag]

    def _await_fill(self, ids: list[str], tag: str, qty: int) -> Fill:
        deadline = time.monotonic() + self.s.order_fill_timeout_s
        mine: list[dict] = []
        while True:
            mine = self._mine(ids, tag)
            if mine and all(_is_terminal(o.get("status", "")) for o in mine):
                break
            if time.monotonic() > deadline:
                break
            time.sleep(1.0)
            if self.on_wait:
                self.on_wait()

        if not mine:
            return Fill("unknown", 0, 0.0, ids, "order not visible in the order book — verify in the Upstox app")

        if not all(_is_terminal(o.get("status", "")) for o in mine):
            for o in mine:
                if not _is_terminal(o.get("status", "")):
                    try:
                        self.cancel(o["order_id"])
                        self.log.warn(f"cancelled unfilled order {o['order_id']} after {self.s.order_fill_timeout_s}s")
                    except Exception as e:  # noqa: BLE001
                        self.log.error(f"cancel failed for {o['order_id']}: {e}")
            time.sleep(1.0)
            mine = self._mine(ids, tag) or mine

        filled, avg = self._aggregate(mine)
        statuses = {(o.get("status") or "").lower() for o in mine}
        msg = "; ".join(sorted({str(o.get("status_message") or "") for o in mine if o.get("status_message")}))
        if filled >= qty:
            return Fill("complete", filled, avg, ids, msg)
        if filled > 0:
            return Fill("partial", filled, avg, ids, msg or f"partial fill {filled}/{qty}")
        if any(s.startswith("reject") for s in statuses):
            return Fill("rejected", 0, 0.0, ids, msg or "rejected")
        if all(_is_terminal(s) for s in statuses):
            return Fill("unfilled", 0, 0.0, ids, msg or "cancelled without fill")
        return Fill("unknown", 0, 0.0, ids, "order still open after cancel attempt — verify in the Upstox app")


def new_tag(strategy_key: str) -> str:
    return f"AD-{strategy_key[:14]}-{datetime.now():%H%M%S%f}"[:40]
