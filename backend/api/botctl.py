"""Start / stop / inspect the bot subprocess."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

from bot import state as st
from bot.auth import is_authenticated, status as auth_status
from core.config import BACKEND_DIR, DATA_DIR, get_settings
from core.store import get_store
from core.timeutil import in_market_hours, now_ist, to_ist
from strategies import get_strategy

LOG_FILE = DATA_DIR / "bot.log"
_proc: subprocess.Popen | None = None


class Conflict(Exception):
    """Request is valid but impossible in the current state (maps to HTTP 409)."""


def start(strategy: str, symbol: str, lots: int, paper: bool | None, params: dict, confirm_live: bool) -> dict:
    global _proc
    s = get_settings()
    get_strategy(strategy, **params)  # validates strategy key + params (ValueError -> 400)
    from core.instruments import get_underlying

    u = get_underlying(symbol)
    effective_paper = s.paper_trade if paper is None else paper
    if not effective_paper and not confirm_live:
        raise ValueError("Live trading needs explicit confirmation (confirm_live=true).")
    if not is_authenticated():
        raise Conflict("Not connected to Upstox. Use 'Connect Upstox' first — the bot needs live data even in paper mode.")
    if st.is_running():
        raise Conflict("A bot is already running. Stop it first.")

    clamped = max(1, min(int(lots), s.max_lots))
    cmd = [
        sys.executable, "-m", "bot.run", "--strategy", strategy, "--symbol", u.symbol, "--lots", str(clamped),
        "--params", json.dumps(params), "--live" if not effective_paper else "--paper",
    ]
    kwargs: dict = {}
    if os.name == "nt":  # survive the dev launcher being closed; positions stay managed until 15:25
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with LOG_FILE.open("ab") as log:
        _proc = subprocess.Popen(cmd, cwd=BACKEND_DIR, stdout=log, stderr=log, stdin=subprocess.DEVNULL, **kwargs)

    # The bot validates auth/config in its first second; surface an immediate failure to the UI.
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if _proc.poll() is not None:
            state = st.read_state() or {}
            raise Conflict(state.get("message") or f"Bot exited immediately (code {_proc.returncode}). See backend/data/bot.log")
        state = st.read_state()
        if state and st.is_running(state) and state.get("pid") == _proc.pid:
            break
        time.sleep(0.25)
    return {"started": True, "mode": "paper" if effective_paper else "live", "lots": clamped, "pid": _proc.pid}


def stop(force: bool = False) -> dict:
    state = st.read_state()
    if not st.is_running(state):
        return {"stopping": False, "detail": "Bot is not running."}
    if force and state and state.get("pid"):
        try:
            os.kill(int(state["pid"]), signal.SIGTERM)  # on Windows this is an immediate terminate
            return {"stopping": True, "forced": True, "detail": "Process terminated. Open positions are NOT flattened — check the Upstox app."}
        except OSError as e:
            raise Conflict(f"Could not terminate bot process: {e}") from None
    st.request_stop()
    return {"stopping": True, "forced": False, "detail": "Stop requested; the bot will flatten and exit within a few seconds."}


def build_status() -> dict:
    s = get_settings()
    state = st.read_state()
    running = st.is_running(state)
    age = st.heartbeat_age(state)
    fresh_today = bool(state and state.get("heartbeat") and to_ist(datetime.fromisoformat(state["heartbeat"])).date() == now_ist().date())

    if running:
        status = state["status"]
    elif state and state.get("status") in st.LIVE_STATUSES and age is not None:
        status = "crashed"  # claimed to be running but the heartbeat went silent
    elif state and fresh_today:
        status = state["status"]
    else:
        status = "idle"

    show = state if (state and (running or fresh_today)) else None
    message = (show or {}).get("message", "")
    if status == "crashed":
        message = "Bot process stopped responding. Any open positions are UNMANAGED — check the Upstox app."
    positions = (show or {}).get("positions", [])
    return {
        "bot": {
            "status": status,
            "running": running,
            "message": message,
            "mode": (show or {}).get("mode"),
            "strategy": (show or {}).get("strategy"),
            "strategy_name": (show or {}).get("strategy_name"),
            "symbol": (show or {}).get("symbol"),
            "lots": (show or {}).get("lots"),
            "params": (show or {}).get("params"),
            "started_at": (show or {}).get("started_at"),
            "spot": (show or {}).get("spot"),
            "vix": (show or {}).get("vix"),
            "last_signal": (show or {}).get("last_signal"),
            "feed_connected": (show or {}).get("feed_connected", False),
            "heartbeat_age_s": round(age, 1) if age is not None else None,
        },
        "positions": positions,
        "risk": (show or {}).get("risk"),
        "logs": (show or {}).get("logs", [])[-30:],
        "settings": {
            "paper_default": s.paper_trade, "max_daily_loss": s.max_daily_loss,
            "max_open_positions": s.max_open_positions, "max_lots": s.max_lots,
            "square_off_on_stop": s.square_off_on_stop,
        },
        "auth": auth_status(),
        "store": get_store().kind,
        "market_open": in_market_hours(),
        "server_time": now_ist().isoformat(),
    }
