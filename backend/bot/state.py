"""File-based IPC between the FastAPI process and the bot subprocess.

  data/bot_state.json   written by the bot ~1/s (status, positions, risk, recent logs, heartbeat)
  data/bot.stop         created by the API to request a graceful stop; the bot deletes it

Files (rather than pipes/signals) keep this identical on Windows, macOS and Linux, and mean the
API can restart without losing track of a running bot.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from core.config import DATA_DIR
from core.timeutil import now_ist

STATE_FILE = DATA_DIR / "bot_state.json"
STOP_FILE = DATA_DIR / "bot.stop"
HEARTBEAT_STALE_S = 45.0  # generous: a slow live order can legitimately block the loop for ~25 s
LIVE_STATUSES = {"starting", "waiting", "running", "stopping"}


def write_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    payload = json.dumps(state, default=str)
    for _ in range(5):  # Windows can briefly refuse os.replace while the API is reading
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, STATE_FILE)
            return
        except OSError:
            time.sleep(0.05)


def read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def heartbeat_age(state: dict | None) -> float | None:
    if not state or not state.get("heartbeat"):
        return None
    try:
        return (now_ist() - datetime.fromisoformat(state["heartbeat"])).total_seconds()
    except ValueError:
        return None


def is_running(state: dict | None = None) -> bool:
    state = state if state is not None else read_state()
    age = heartbeat_age(state)
    return bool(state and state.get("status") in LIVE_STATUSES and age is not None and age < HEARTBEAT_STALE_S)


def request_stop() -> None:
    STOP_FILE.write_text(now_ist().isoformat(), encoding="utf-8")


def stop_requested() -> bool:
    return STOP_FILE.exists()


def clear_stop() -> None:
    STOP_FILE.unlink(missing_ok=True)
