"""Activity log: a record of what was done in Axiom and what happened (bot start/stop, backtests, logins, report
loads, errors, tab navigation ...). It feeds the Logs tab.

Writing never blocks the caller: events go on a queue drained by a background thread (a Neon round trip is
~0.3-1s). A row that still can't be stored after retries is appended to data/failed_activity.jsonl, so nothing
is lost silently. Recording is best-effort and never raises into the request that triggered it.

Secrets are redacted before anything is queued: keys that look like credentials are replaced, and so are
JWT-shaped and database-URL-shaped strings.
"""
from __future__ import annotations

import atexit
import json
import logging
import queue
import re
import threading
import time
from typing import Any

from core.config import DATA_DIR
from core.store import get_store
from core.timeutil import utc_now_iso

FAILED_FILE = DATA_DIR / "failed_activity.jsonl"
_py = logging.getLogger("axiom.activity")

CATEGORIES = ("navigation", "bot", "backtest", "reports", "suggestions", "auth", "system")
LEVELS = ("INFO", "WARN", "ERROR")

_SECRET_KEY = re.compile(r"(token|secret|passw|authoriz|api[_-]?key|credential|cookie|signature)", re.I)
_SECRET_EXACT = {"code", "state", "key"}  # OAuth callback params / bare "key"; NOT instrument_key etc.
_SECRET_VALUE = re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|postgres(ql)?://\S+|sk-ant-\S+)")
MAX_STR, MAX_DETAILS_BYTES, MAX_DEPTH = 500, 8000, 6


def redact(obj: Any, _depth: int = 0) -> Any:
    """Copy of `obj` safe to store: credential-looking keys and values masked, long strings cut, depth capped."""
    if _depth > MAX_DEPTH:
        return "…"
    if isinstance(obj, dict):
        return {
            str(k): ("[redacted]" if _SECRET_KEY.search(str(k)) or str(k).lower() in _SECRET_EXACT else redact(v, _depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple, set)):
        return [redact(v, _depth + 1) for v in list(obj)[:200]]
    if isinstance(obj, str):
        s = _SECRET_VALUE.sub("[redacted]", obj)
        return s if len(s) <= MAX_STR else s[:MAX_STR] + "…"
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    return redact(str(obj), _depth + 1)


def category_for(path: str) -> str:
    """Which Logs category an API path belongs to (used for errors raised by the exception handlers)."""
    for prefix, cat in (("/bot", "bot"), ("/backtest", "backtest"), ("/trades", "reports"), ("/suggestions", "suggestions"), ("/auth", "auth")):
        if path.startswith(prefix):
            return cat
    return "system"


# Polled every few seconds by the UI: an error here would repeat forever and drown the log.
QUIET_PATHS = ("/status", "/health", "/market", "/orders", "/instruments", "/strategies", "/auth/status", "/logs", "/bot/logs")


def is_quiet(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in QUIET_PATHS)


class ActivityLog:
    def __init__(self) -> None:
        self._q: queue.Queue[dict | threading.Event] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._exit_hook = False
        self._recent: dict[tuple, float] = {}

    # ---- public
    def record(self, category: str, action: str, summary: str, *, level: str = "INFO", details: Any = None, dedupe_s: float = 0.0) -> None:
        try:
            if dedupe_s:
                key, now = (category, action, summary), time.monotonic()
                if now - self._recent.get(key, -1e9) < dedupe_s:
                    return
                self._recent[key] = now
                if len(self._recent) > 500:  # keep the map small
                    self._recent = {k: t for k, t in self._recent.items() if now - t < dedupe_s}
            row = {
                "created_at": utc_now_iso(),
                "category": category if category in CATEGORIES else "system",
                "action": str(action)[:60],
                "summary": str(redact(summary))[:MAX_STR],
                "level": level if level in LEVELS else "INFO",
                "details": self._pack(details),
            }
            self._ensure_thread()
            self._q.put(row)
        except Exception:  # noqa: BLE001 - logging must never break the action being logged
            _py.exception("could not queue activity event")

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until everything queued so far has been written (or given up on). True if it finished in time."""
        if self._thread is None:
            return True
        marker = threading.Event()
        self._q.put(marker)
        return marker.wait(timeout)

    # ---- internals
    @staticmethod
    def _pack(details: Any) -> Any:
        if details is None:
            return None
        safe = redact(details)
        if len(json.dumps(safe, default=str)) > MAX_DETAILS_BYTES:
            return {"_truncated": True, "note": "details too large to store"}
        return safe

    def _ensure_thread(self) -> None:
        with self._start_lock:
            if not self._exit_hook:
                get_store()  # create the store first so its pool-close hook is registered before ours (atexit is LIFO)
                atexit.register(self.flush, 5.0)
                self._exit_hook = True
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._drain, name="activity-writer", daemon=True)
                self._thread.start()

    def _drain(self) -> None:
        while True:
            item = self._q.get()
            if isinstance(item, threading.Event):
                item.set()
                continue
            for attempt in range(3):
                try:
                    get_store().insert("activity_logs", item)
                    break
                except Exception as e:  # noqa: BLE001 - any storage failure goes through retry, then the dump file
                    if attempt == 2:
                        _py.error("could not persist activity row (%s); saved to %s", e, FAILED_FILE.name)
                        with FAILED_FILE.open("a", encoding="utf-8") as f:
                            f.write(json.dumps({"row": item, "error": str(e)[:300]}, default=str) + "\n")
                    else:
                        time.sleep(1.0 * (attempt + 1))


_log = ActivityLog()
record = _log.record
flush = _log.flush
