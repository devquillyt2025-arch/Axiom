"""The Logs tab: one newest-first timeline merging what you did (activity_logs), what the bot engine said
(bot_logs) and the orders it placed (trades)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core import activity
from core.store import get_store
from core.timeutil import day_start_utc_iso, today_ist

router = APIRouter(tags=["logs"])

Category = Literal["all", "navigation", "bot", "backtest", "reports", "suggestions", "auth", "system", "engine", "trade"]
Level = Literal["all", "INFO", "WARN", "ERROR"]
Range = Literal["today", "7d", "30d", "all"]


class EventBody(BaseModel):
    """Something only the browser knows happened (a tab was opened, a CSV exported)."""

    category: Literal["navigation", "reports", "backtest"]
    action: str = Field(min_length=1, max_length=60)
    summary: str = Field(min_length=1, max_length=300)
    details: dict[str, Any] | None = None


@router.post("/logs/event")
def log_event(body: EventBody) -> dict:
    activity.record(body.category, body.action, body.summary, details=body.details)
    return {"ok": True}


def _since(rng: Range) -> str | None:
    days = {"today": 0, "7d": 6, "30d": 29}.get(rng)
    return None if days is None else day_start_utc_iso(today_ist() - timedelta(days=days))


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _trade_entry(r: dict) -> dict:
    meta = r.get("meta") or {}
    bits = [f"{r['action']} {r['instrument']} ×{int(r['quantity'])} @ {float(r['price']):.2f}", "paper" if r.get("is_paper") else "LIVE"]
    if r.get("pnl") is not None:
        bits.append(f"P&L {float(r['pnl']):+,.2f}")
    if meta.get("reason"):
        bits.append(str(meta["reason"]))
    details = {"order_id": r.get("order_id"), "status": r.get("status"), "strategy": r.get("strategy_tag"), "is_paper": r.get("is_paper"), **meta}
    return {"id": r["id"], "created_at": r["created_at"], "source": "trade", "category": "trade", "action": r["action"].lower(),
            "level": "INFO", "summary": " · ".join(bits), "details": details}


@router.get("/logs")
def logs(
    limit: int = Query(200, ge=1, le=500),
    before: str | None = Query(None, description="ISO timestamp: only entries older than this (paging cursor)"),
    range: Range = "today",
    category: Category = "all",
    level: Level = "all",
) -> dict:
    store = get_store()
    filters: list = []
    if (since := _since(range)) is not None:
        filters.append(("created_at", "gte", since))
    if before:
        _when(before)  # malformed cursor -> ValueError -> 400
        filters.append(("created_at", "lt", before))
    lvl = [("level", "eq", level)] if level != "all" else []

    jobs: dict[str, tuple[str, list]] = {}
    if category not in ("engine", "trade"):
        jobs["activity"] = ("activity_logs", [*filters, *lvl, *([("category", "eq", category)] if category != "all" else [])])
    if category in ("all", "engine"):
        jobs["bot"] = ("bot_logs", [*filters, *lvl])
    if category in ("all", "trade") and level in ("all", "INFO"):
        jobs["trade"] = ("trades", filters)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(store.select, table, f, "created_at", True, limit) for name, (table, f) in jobs.items()}
        fetched = {name: fut.result() for name, fut in futures.items()}

    entries: list[dict] = []
    for r in fetched.get("activity", []):
        entries.append({"id": r["id"], "created_at": r["created_at"], "source": "activity", "category": r["category"], "action": r["action"],
                        "level": r["level"], "summary": r["summary"], "details": r.get("details")})
    for r in fetched.get("bot", []):
        entries.append({"id": r["id"], "created_at": r["created_at"], "source": "bot", "category": "engine", "action": "log",
                        "level": r["level"], "summary": r["message"], "details": None})
    entries.extend(_trade_entry(r) for r in fetched.get("trade", []))

    entries.sort(key=lambda e: _when(e["created_at"]), reverse=True)
    has_more = len(entries) > limit or any(len(rows) >= limit for rows in fetched.values())
    entries = entries[:limit]
    return {
        "entries": entries, "next_before": entries[-1]["created_at"] if has_more and entries else None,
        "range": range, "category": category, "level": level, "store": store.kind,  # the filters echo lets the UI discard stale responses
    }
