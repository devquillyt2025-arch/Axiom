"""The trading bot process.  Spawned by the API:  python -m bot.run --strategy ... --symbol ... [--live]

Loop (1 s tick), active 09:15–15:25 IST on trading days:
  1. refresh prices (WebSocket feed, REST LTP fallback)
  2. mark positions to market, enforce the daily-loss limit, check stops/targets on every tick,
     square everything off at 15:15
  3. when a candle closes, run the strategy on the closed bars: exits first, then at most one entry
  4. publish state (positions, risk, logs, heartbeat) for the API/UI

Safety defaults: paper mode unless explicitly told otherwise, one position at a time, lots hard-capped
by MAX_LOTS, new entries only 09:20–14:45, no overnight positions.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time as _time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd

from bot import state as st
from bot.auth import AuthRequired, is_authenticated
from bot.contracts import Contract, ContractResolver
from bot.executor import Executor, Fill, new_tag
from bot.feed import LiveFeed
from bot.logger import BotLogger
from bot.risk import RiskManager
from bot.strategy import Context, OpenPosition, Signal, exit_levels, leg_for, stop_or_target_hit
from core.config import Settings, get_settings
from core.instruments import VIX_KEY, get_underlying
from core.store import Store, get_store
from core.timeutil import (
    BOT_STOP, ENTRY_CUTOFF, ENTRY_START, IST, MARKET_OPEN, SQUARE_OFF, day_start_utc_iso, now_ist,
)
from core.upstox import UpstoxClient
from strategies import get_strategy

MAX_CONSECUTIVE_ERRORS = 60
EXIT_RETRY_GAP_S = 3.0


def floor_bar(now: datetime, tf: int) -> datetime:
    open_dt = datetime.combine(now.date(), MARKET_OPEN, tzinfo=IST)
    mins = int((now - open_dt).total_seconds() // 60)
    return open_dt + timedelta(minutes=(mins // tf) * tf)


def _pos_to_raw(p: OpenPosition, c: Contract) -> dict:
    d = asdict(p)
    d["entry_time"] = p.entry_time.isoformat()
    d["contract"] = asdict(c)
    return d


def _pos_from_raw(d: dict) -> tuple[OpenPosition, Contract]:
    d = dict(d)
    c = Contract(**d.pop("contract"))
    d["entry_time"] = datetime.fromisoformat(d["entry_time"])
    return OpenPosition(**d), c


class Bot:
    def __init__(
        self, *, strategy_key: str, symbol: str, lots: int, paper: bool, params: dict | None = None,
        settings: Settings | None = None, store: Store | None = None, client: Any = None,
        candles_fn: Callable[[str, int, int], pd.DataFrame] | None = None,
        clock: Callable[[], datetime] | None = None, feed: Any = None, use_feed: bool = True,
    ):
        self.s = settings or get_settings()
        self.paper = paper
        self.clock = clock or now_ist
        self.u = get_underlying(symbol)
        self.strategy = get_strategy(strategy_key, **(params or {}))
        self.log = BotLogger(store or get_store())
        self.store = self.log.store
        self.client = client or UpstoxClient()
        if candles_fn is None:
            from core import marketdata
            candles_fn = marketdata.candles
        self.candles_fn = candles_fn
        self.risk = RiskManager(self.s.max_daily_loss, self.s.max_open_positions, self.s.max_lots)
        self.lots = self.risk.clamp_lots(lots)
        # Keep the heartbeat fresh while the executor waits on a slow live order, otherwise the API
        # would think the bot died and let a second instance start (= double orders).
        self.executor = Executor(self.client, paper, self.log, self.s, on_wait=lambda: self._write_state(self.clock()))
        self.resolver = ContractResolver(self.client)
        self.feed = feed if feed is not None else (LiveFeed(self.client, self.log) if use_feed else _NoFeed())
        self.use_feed = use_feed and feed is None

        self.positions: list[OpenPosition] = []
        self.contracts: dict[str, Contract] = {}
        self.status = "starting"
        self.message = ""
        self.started_at = self.clock()
        self.spot: float | None = None
        self.vix: float | None = None
        self.last_signal: dict | None = None
        self._evaluated_bar: datetime | None = None
        self._last_fetch_try = 0.0
        self._vix_at = 0.0
        self._exit_try: dict[str, float] = {}
        self._exchange_ok: tuple[float, bool] = (0.0, True)
        self._errors = 0
        self._stop_signal = False
        self._halt_logged = False
        self.finished = False

    # ================================================================== lifecycle
    def start(self) -> None:
        self.log.info(
            f"Bot starting — {'PAPER' if self.paper else 'LIVE'} | {self.strategy.name} | {self.u.symbol} | "
            f"{self.lots} lot(s) | params {self.strategy.p}"
        )
        self._restore()
        keys = [self.u.index_key, VIX_KEY, *[p.instrument_key for p in self.positions]]
        if self.use_feed:
            self.feed.start(keys)
        self.status = "waiting"

    def run_forever(self) -> int:
        self.start()
        while not self.finished:
            t0 = _time.monotonic()
            try:
                if not self.tick():
                    break
                self._errors = 0
            except AuthRequired as e:
                self.log.error(f"Upstox session invalid: {e}")
                self._shutdown(f"auth: {e}", error=True)
                break
            except Exception as e:  # noqa: BLE001 - the loop must survive transient failures
                self._errors += 1
                self.log.error(f"tick failed ({self._errors}/{MAX_CONSECUTIVE_ERRORS}): {type(e).__name__}: {e}")
                if self._errors >= MAX_CONSECUTIVE_ERRORS:
                    self._shutdown("too many consecutive errors", error=True)
                    break
            _time.sleep(max(0.0, 1.0 - (_time.monotonic() - t0)))
        return 0 if self.status != "error" else 1

    def request_stop(self, *_: Any) -> None:
        self._stop_signal = True

    # ================================================================== main tick
    def tick(self) -> bool:
        now = self.clock()
        if st.stop_requested() or self._stop_signal:
            self._shutdown("Stop requested")
            return False
        weekday, t = now.weekday() < 5, now.time()
        if not weekday or t >= BOT_STOP:
            if self.positions and weekday:
                self._shutdown("Market window closed (15:25)")
            else:
                self._shutdown("Market closed — start the bot on a trading day before 15:25 IST")
            return False
        if t < MARKET_OPEN:
            self.status, self.message = "waiting", f"Waiting for market open at {MARKET_OPEN:%H:%M}"
            self._write_state(now)
            return True
        if not self._exchange_open():
            self.status, self.message = "waiting", f"{self.u.exchange} is not in a normal open session (holiday?)"
            self._refresh_prices()
            self._manage_positions(now)
            self._write_state(now)
            return True

        self.status = "running"
        self.message = "halted: " + self.risk.halt_reason if self.risk.halted else ""
        self._refresh_prices()
        self._manage_positions(now)
        self._maybe_evaluate(now)
        self._write_state(now)
        return True

    # ================================================================== prices
    def _exchange_open(self) -> bool:
        ts, ok = self._exchange_ok
        if _time.monotonic() - ts < 60:
            return ok
        try:
            status = self.client.market_status(self.u.exchange)
            ok = status.endswith("_OPEN") and not status.startswith("PRE")
        except Exception as e:  # noqa: BLE001 - if the check itself fails, don't block risk management
            self.log.warn(f"market status check failed ({e}); assuming open")
            ok = True
        self._exchange_ok = (_time.monotonic(), ok)
        return ok

    def _refresh_prices(self) -> None:
        keys = [self.u.index_key, *[p.instrument_key for p in self.positions]]
        prices: dict[str, float | None] = {k: self.feed.get(k) for k in keys}
        missing = [k for k, v in prices.items() if v is None]
        if missing:
            for k, v in self.client.ltp(missing).items():
                prices[k] = v
        if prices.get(self.u.index_key):
            self.spot = float(prices[self.u.index_key])  # type: ignore[arg-type]
        for p in self.positions:
            px = prices.get(p.instrument_key)
            if px:
                p.last_price = float(px)
        if _time.monotonic() - self._vix_at > 30:
            self._vix_at = _time.monotonic()
            v = self.feed.get(VIX_KEY, 60) or self.client.ltp([VIX_KEY]).get(VIX_KEY)
            if v:
                self.vix = float(v)

    # ================================================================== position management
    def _manage_positions(self, now: datetime) -> None:
        self.risk.update_mtm(sum(p.unrealised for p in self.positions))
        if self.risk.halted:
            if not self._halt_logged:
                self._halt_logged = True
                self.log.error(f"RISK HALT — {self.risk.halt_reason}. No new entries; flattening.")
            for p in list(self.positions):
                self._exit(p, "Daily loss limit")
            return
        for p in list(self.positions):
            hit = stop_or_target_hit(p, p.last_price)
            if hit:
                self._exit(p, "Stop-loss" if hit == "SL" else "Target")
        if now.time() >= SQUARE_OFF:
            for p in list(self.positions):
                self._exit(p, "Square-off")

    def _exit(self, p: OpenPosition, reason: str) -> None:
        if _time.monotonic() - self._exit_try.get(p.id, 0.0) < EXIT_RETRY_GAP_S:
            return
        self._exit_try[p.id] = _time.monotonic()
        c = self.contracts[p.id]
        close_side = "BUY" if p.side == "SELL" else "SELL"
        fill = self.executor.execute(c, close_side, p.qty, p.last_price, new_tag(self.strategy.key))
        if fill.status == "unknown":
            self._trading_fault(f"EXIT order state unknown for {p.trading_symbol}: {fill.message}")
        if fill.filled_qty <= 0:
            self.log.error(f"exit of {p.trading_symbol} ({reason}) not filled [{fill.status}] {fill.message} — will retry")
            return
        qty = min(fill.filled_qty, p.qty)
        pnl = ((p.entry_price - fill.avg_price) if p.side == "SELL" else (fill.avg_price - p.entry_price)) * qty
        self.risk.record_order()
        self.risk.record_realized(pnl)
        self.log.record_trade(
            instrument=p.trading_symbol, action=close_side, quantity=qty, price=fill.avg_price,
            order_id=",".join(fill.order_ids), status=fill.status, strategy_tag=p.strategy, pnl=pnl,
            is_paper=self.paper,
            meta={"reason": reason, "entry_price": p.entry_price, "underlying": p.underlying, "instrument_key": p.instrument_key,
                  "side_opened": p.side, "gross": True},
        )
        self.log.info(f"EXIT {p.trading_symbol} x{qty} @ {fill.avg_price:.2f} ({reason}) P&L ₹{pnl:,.0f}")
        if qty >= p.qty:
            self.positions.remove(p)
            self.contracts.pop(p.id, None)
            self.feed.unsubscribe([p.instrument_key])
        else:
            p.qty -= qty

    def _trading_fault(self, msg: str) -> None:
        """An order's outcome is uncertain: stop opening anything new until a human checks."""
        self.log.error(f"TRADING FAULT — {msg}. New entries disabled; verify positions in the Upstox app.")
        self.risk.halted = True
        self.risk.halt_reason = msg[:200]

    # ================================================================== strategy evaluation
    def _maybe_evaluate(self, now: datetime) -> None:
        tf = self.strategy.timeframe_minutes
        cur = floor_bar(now, tf)
        if cur == self._evaluated_bar:
            return
        since = (now - cur).total_seconds()
        if since < 3:  # give the exchange a moment to finalise the candle
            return
        if cur == datetime.combine(now.date(), MARKET_OPEN, tzinfo=IST):
            self._evaluated_bar = cur  # first bar of the day is still forming; nothing closed yet today
            return
        if _time.monotonic() - self._last_fetch_try < 3:
            return
        self._last_fetch_try = _time.monotonic()

        df = self.candles_fn(self.u.symbol, tf, 7)
        closed = df[df.index + timedelta(minutes=tf) <= now]
        want_last = cur - timedelta(minutes=tf)
        if closed.empty or closed.index[-1].to_pydatetime() != want_last:
            if since < 45:
                return  # candle not published yet — retry on the next tick
            self.log.warn(f"candle {want_last:%H:%M} never arrived; skipping this evaluation rather than trading on stale data")
            self._evaluated_bar = cur
            return
        self._evaluated_bar = cur

        prepared = self.strategy.prepare(closed)
        i = len(prepared) - 1
        spot = self.spot or float(prepared["close"].iloc[-1])
        ctx = Context(df=prepared, i=i, spot=spot, vix=self.vix, underlying=self.u.symbol, timeframe_minutes=tf)

        for p in list(self.positions):
            reason = self.strategy.should_exit(ctx, p)
            if reason:
                self.log.info(f"strategy exit signal for {p.trading_symbol}: {reason}")
                self._exit(p, reason)

        if i < self.strategy.min_bars() or not (ENTRY_START <= now.time() <= ENTRY_CUTOFF):
            return
        sig = self.strategy.should_enter(ctx)
        if sig:
            self.last_signal = {"time": now.isoformat(), "direction": sig.direction, "reason": sig.reason}
            self.log.info(f"signal {sig.direction}: {sig.reason}")
            self._enter(sig, now)

    def _enter(self, sig: Signal, now: datetime) -> None:
        ok, why = self.risk.can_enter(len(self.positions))
        if not ok:
            self.log.warn(f"entry blocked: {why}")
            return
        opt, side = leg_for(sig.direction, self.strategy.option_side)
        if self.spot is None:
            self.log.warn("entry skipped: no spot price")
            return
        try:
            c = self.resolver.atm(self.u, self.spot, opt, now.date())
            ltp = self.client.ltp([c.instrument_key]).get(c.instrument_key)
        except Exception as e:  # noqa: BLE001
            self.log.error(f"entry skipped: could not resolve {opt} contract / price: {e}")
            return
        if not ltp or ltp <= 0:
            self.log.warn(f"entry skipped: no price for {c.trading_symbol}")
            return
        qty = self.lots * c.lot_size
        fill: Fill = self.executor.execute(c, side, qty, float(ltp), new_tag(self.strategy.key))
        if fill.status == "unknown":
            self._trading_fault(f"ENTRY order state unknown for {c.trading_symbol}: {fill.message}")
        if fill.filled_qty <= 0:
            self.log.warn(f"entry not filled [{fill.status}] {c.trading_symbol}: {fill.message}")
            return
        sl_pct = sig.sl_pct or float(self.strategy.p["sl_pct"])
        tgt_pct = sig.target_pct or float(self.strategy.p["target_pct"])
        sl, tgt = exit_levels(side, fill.avg_price, sl_pct, tgt_pct)
        pos = OpenPosition(
            id=uuid.uuid4().hex[:10], strategy=self.strategy.key, underlying=self.u.symbol,
            instrument_key=c.instrument_key, trading_symbol=c.trading_symbol, option_type=opt, strike=c.strike,
            expiry=c.expiry, side=side, qty=fill.filled_qty, lot_size=c.lot_size, entry_price=fill.avg_price,
            entry_time=now, last_price=float(ltp), direction=sig.direction, sl_price=sl, target_price=tgt, reason=sig.reason,
        )
        self.positions.append(pos)
        self.contracts[pos.id] = c
        self.feed.subscribe([c.instrument_key])
        self.risk.record_order()
        self.log.record_trade(
            instrument=c.trading_symbol, action=side, quantity=fill.filled_qty, price=fill.avg_price,
            order_id=",".join(fill.order_ids), status=fill.status, strategy_tag=self.strategy.key, pnl=None,
            is_paper=self.paper,
            meta={"reason": sig.reason, "underlying": self.u.symbol, "instrument_key": c.instrument_key,
                  "sl": round(sl, 2), "target": round(tgt, 2)},
        )
        self.log.info(
            f"ENTRY {side} {c.trading_symbol} x{fill.filled_qty} @ {fill.avg_price:.2f} | SL {sl:.2f} | target {tgt:.2f} | {sig.reason}"
        )

    # ================================================================== state / shutdown
    def _restore(self) -> None:
        """Same-day restart: reload today's realised P&L and any open positions the last run left."""
        try:
            rows = self.store.select("trades", [("created_at", "gte", day_start_utc_iso()), ("is_paper", "eq", self.paper)], limit=2000)
            self.risk.realized = sum(float(r["pnl"]) for r in rows if r.get("pnl") is not None)
            self.risk.orders_fired = len(rows)
            self.risk.update_mtm(0.0)
            if rows:
                self.log.info(f"restored today's tally: {len(rows)} orders, realised ₹{self.risk.realized:,.0f}")
        except Exception as e:  # noqa: BLE001
            self.log.warn(f"could not restore today's P&L from the store: {e}")
        prev = st.read_state() or {}
        raws = prev.get("restorable") or []
        for raw in raws:
            try:
                pos, c = _pos_from_raw(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if pos.entry_time.date() != self.clock().date() or prev.get("mode") != ("paper" if self.paper else "live"):
                self.log.error(f"found an open position from a previous session ({pos.trading_symbol}) — NOT managed; check it manually")
                continue
            self.positions.append(pos)
            self.contracts[pos.id] = c
            self.log.warn(f"restored open position {pos.trading_symbol} x{pos.qty} @ {pos.entry_price}")

    def _write_state(self, now: datetime) -> None:
        st.write_state(
            {
                "status": self.status, "message": self.message, "heartbeat": now.isoformat(), "pid": os.getpid(),
                "started_at": self.started_at.isoformat(), "mode": "paper" if self.paper else "live",
                "strategy": self.strategy.key, "strategy_name": self.strategy.name, "params": self.strategy.p,
                "symbol": self.u.symbol, "lots": self.lots, "spot": self.spot, "vix": self.vix,
                "positions": [p.to_dict() for p in self.positions], "risk": self.risk.stats(),
                "last_signal": self.last_signal, "feed_connected": bool(getattr(self.feed, "connected", False)),
                "logs": list(self.log.recent)[-30:],
                "restorable": [_pos_to_raw(p, self.contracts[p.id]) for p in self.positions if p.id in self.contracts],
                "data_source": "upstox",
            }
        )

    def _shutdown(self, reason: str, error: bool = False) -> None:
        if self.finished:
            return
        self.status = "stopping"
        self.message = reason
        self.log.info(f"Shutting down: {reason}")
        self._write_state(self.clock())
        flatten = self.positions and (self.s.square_off_on_stop or reason.startswith("Market window"))
        if flatten:
            for attempt in range(1, 5):
                self._exit_try.clear()
                self._refresh_prices_safely()
                for p in list(self.positions):
                    self._exit(p, f"Bot stop ({reason})")
                if not self.positions:
                    break
                _time.sleep(2)
        if self.positions:
            self.log.error(
                f"{len(self.positions)} position(s) still OPEN at shutdown: "
                + ", ".join(p.trading_symbol for p in self.positions)
                + " — close them in the Upstox app."
            )
        self.status = "error" if error else "stopped"
        try:
            self.feed.stop()
        except Exception:  # noqa: BLE001
            pass
        self._write_state(self.clock())
        self.log.close()
        st.clear_stop()
        self.finished = True

    def _refresh_prices_safely(self) -> None:
        try:
            self._refresh_prices()
        except Exception as e:  # noqa: BLE001
            self.log.warn(f"price refresh failed during shutdown: {e}")


class _NoFeed:
    connected = False

    def start(self, keys): pass
    def stop(self): pass
    def subscribe(self, keys): pass
    def unsubscribe(self, keys): pass
    def get(self, key, max_age=5.0): return None


# ====================================================================== CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Axiom trading bot")
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--lots", type=int, default=1)
    ap.add_argument("--params", default="{}", help="JSON object of strategy parameters")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--paper", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)

    s = get_settings()
    paper = False if args.live else True if args.paper else s.paper_trade

    prev = st.read_state()
    if st.is_running(prev):
        print("Another bot instance is already running (fresh heartbeat). Refusing to start a second one.", file=sys.stderr)
        return 3
    st.clear_stop()

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        # keep any restorable positions from the previous run so a later start can still pick them up
        st.write_state({"status": "error", "message": msg, "heartbeat": now_ist().isoformat(), "mode": "paper" if paper else "live",
                        "positions": [], "restorable": (prev or {}).get("restorable", [])})
        return 2

    if not is_authenticated():
        return fail("Not connected to Upstox (or the session expired). Log in from the app first — the bot needs live market data even in paper mode.")
    try:
        bot = Bot(strategy_key=args.strategy, symbol=args.symbol, lots=args.lots, paper=paper, params=json.loads(args.params))
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return fail(f"Invalid bot configuration: {e}")

    signal.signal(signal.SIGINT, bot.request_stop)
    signal.signal(signal.SIGTERM, bot.request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, bot.request_stop)
    return bot.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
