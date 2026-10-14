"""Writes to Neon `trades` + `bot_logs` (or the local SQLite fallback) without ever blocking
the trading loop: rows go on a queue drained by a background thread. A row that still can't be
written after retries is appended to data/failed_writes.jsonl so no trade record is ever lost
silently — reconcile it by hand or re-import it.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque

from core.config import DATA_DIR
from core.store import Store, get_store
from core.timeutil import utc_now_iso

FAILED_FILE = DATA_DIR / "failed_writes.jsonl"
_py = logging.getLogger("axiom.bot")


class BotLogger:
    def __init__(self, store: Store | None = None):
        self.store = store or get_store()
        self._q: queue.Queue[tuple[str, dict] | None] = queue.Queue()
        self.recent: deque[dict] = deque(maxlen=100)  # surfaced in the bot state file
        self._t = threading.Thread(target=self._drain, name="bot-log-writer", daemon=True)
        self._t.start()

    # ---- public
    def log(self, level: str, message: str) -> None:
        level = level.upper()
        getattr(_py, {"WARN": "warning"}.get(level, level.lower()), _py.info)(message)
        row = {"level": level, "message": message[:2000], "created_at": utc_now_iso()}
        self.recent.append(row)
        self._q.put(("bot_logs", row))

    def info(self, m: str) -> None: self.log("INFO", m)
    def warn(self, m: str) -> None: self.log("WARN", m)
    def error(self, m: str) -> None: self.log("ERROR", m)

    def record_trade(
        self, *, instrument: str, action: str, quantity: int, price: float, order_id: str, status: str,
        strategy_tag: str, pnl: float | None, is_paper: bool, meta: dict | None = None,
    ) -> dict:
        row = {
            "created_at": utc_now_iso(), "instrument": instrument, "action": action, "quantity": int(quantity),
            "price": round(float(price), 2), "order_id": order_id, "status": status, "strategy_tag": strategy_tag,
            "pnl": None if pnl is None else round(float(pnl), 2), "is_paper": bool(is_paper), "meta": meta or {},
        }
        self._q.put(("trades", row))
        return row

    def close(self, timeout: float = 15.0) -> None:
        """Flush pending rows (call before the process exits)."""
        self._q.put(None)
        self._t.join(timeout)

    # ---- worker
    def _drain(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            table, row = item
            for attempt in range(4):
                try:
                    self.store.insert(table, row)
                    break
                except Exception as e:  # noqa: BLE001 - any storage failure falls through to the retry/dump path
                    if attempt == 3:
                        _py.error("could not persist %s row after retries (%s); saved to %s", table, e, FAILED_FILE.name)
                        with FAILED_FILE.open("a", encoding="utf-8") as f:
                            f.write(json.dumps({"table": table, "row": row, "error": str(e)[:300]}, default=str) + "\n")
                    else:
                        time.sleep(1.5 * (attempt + 1))
