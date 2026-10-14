"""AI trade-idea cards via the Claude API (Haiku by default, for cost).

Flow: build a compact numeric market context from live data -> ask Claude for 2-3 options-selling
setups as schema-validated JSON (structured outputs, so the UI never has to parse prose) -> cache
the result so a page load doesn't re-bill. These are *ideas to study*, not advice; the UI says so.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from core import marketdata
from core.config import get_settings
from core.instruments import get_underlying
from core.store import get_store
from core.timeutil import now_ist, today_ist, utc_now_iso

CACHE_MINUTES = 30
_locks: dict[str, threading.Lock] = {}


class Setup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Short setup name, e.g. 'Short strangle 24300/24800'")
    strategy_type: str = Field(description="e.g. Short Strangle, Iron Condor, Bull Put Spread, Short Straddle")
    bias: Literal["Bullish", "Bearish", "Neutral"]
    entry_zone: str = Field(description="Strikes/legs to sell (and hedge) and the spot/premium zone to enter")
    stop_loss: str = Field(description="Concrete stop: spot level and/or premium multiple, and the adjustment rule")
    target: str = Field(description="Concrete profit target, e.g. exit at 50% premium decay")
    risk_reward: str = Field(description="Approximate risk:reward such as '1 : 1.6' with a one-line basis")
    rationale: str = Field(description="2-3 sentences tying the setup to the supplied numbers (PCR, OI walls, VIX, expected move)")


class Suggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(description="Two-sentence read of today's market from the supplied context only")
    setups: list[Setup]


SYSTEM = """You are an options-market analyst helping an Indian retail trader study index option-selling ideas.

Rules:
- Use ONLY the numbers in the provided context. Never invent prices, strikes, OI, or events. Strikes you mention must exist in the supplied option chain data.
- Prefer defined-risk structures (hedged spreads, iron condors) and say plainly when a naked position carries open-ended risk.
- Be concrete: strikes, spot levels, premium levels, and what to do if the stop is hit.
- Give exactly 2 or 3 setups with different risk profiles, and be honest about uncertainty. Do not promise outcomes.
- This is educational analysis, not investment advice."""

USER_TMPL = (
    "Given this market context, suggest 2-3 options selling setups for today with entry, SL, target, rationale.\n\n"
    "Market context (JSON):\n{context}"
)


class SuggestError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- context
def build_context(symbol: str) -> dict:
    u = get_underlying(symbol)
    chain = marketdata.option_chain(u.symbol, None, width=15)
    snap = marketdata.live_snapshot(u.symbol, interval=15, days=3)
    rows = chain["rows"]
    atm_row = min(rows, key=lambda r: abs(r["strike"] - chain["atm"])) if rows else None
    straddle = (atm_row["ce"]["ltp"] + atm_row["pe"]["ltp"]) if atm_row else None

    def top(side: str, n: int = 3) -> list[dict]:
        ranked = sorted(rows, key=lambda r: r[side]["oi"], reverse=True)[:n]
        return [{"strike": r["strike"], "oi": int(r[side]["oi"]), "oi_change": int(r[side]["oi_change"]), "ltp": r[side]["ltp"]} for r in ranked]

    expiry = datetime.fromisoformat(chain["expiry"]).date()
    return {
        "as_of_ist": now_ist().strftime("%Y-%m-%d %H:%M"),
        "data_source": snap["source"],
        "underlying": u.name,
        "spot": round(snap["ltp"], 2),
        "change_pct": round(snap["change_pct"], 2),
        "day_open_high_low": [round(snap["ohlc"][k], 2) for k in ("open", "high", "low")],
        "prev_close": round(snap["prev_close"], 2),
        "india_vix": snap["vix"],
        "expiry": chain["expiry"],
        "days_to_expiry": (expiry - today_ist()).days,
        "atm_strike": chain["atm"],
        "atm_straddle_premium": round(straddle, 2) if straddle is not None else None,
        "pcr": round(chain["pcr"], 3) if chain["pcr"] is not None else None,
        "max_pain": chain["max_pain"],
        "oi_resistance_strike": chain["resistance"],
        "oi_support_strike": chain["support"],
        "top_call_oi_strikes": top("ce"),
        "top_put_oi_strikes": top("pe"),
        "mood_heuristic": chain["mood"]["label"],
        "strike_step": u.strike_step,
        "lot_size_hint": u.fallback_lot_size,
    }


# --------------------------------------------------------------------------- generation
def _client() -> anthropic.Anthropic:
    s = get_settings()
    if not s.anthropic_api_key:
        raise SuggestError("ANTHROPIC_API_KEY is not set. Add it to .env and restart the API.", 503)
    return anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=60.0, max_retries=2)


def generate(symbol: str, refresh: bool = False) -> dict:
    u = get_underlying(symbol)
    if marketdata.source() != "upstox":
        raise SuggestError("Connect Upstox first — suggestions are only generated from live market data.", 409)
    lock = _locks.setdefault(u.symbol, threading.Lock())
    with lock:
        store = get_store()
        if not refresh:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CACHE_MINUTES)).isoformat()
            rows = store.select("suggestions", [("symbol", "eq", u.symbol), ("created_at", "gte", cutoff)], limit=1)
            if rows:
                r = rows[0]
                return {**r["setups_json"], "context": r["context_json"], "generated_at": r["created_at"], "model": r["model"], "cached": True}

        context = build_context(u.symbol)
        s = get_settings()

        try:
            resp = _client().messages.parse(
                model=s.anthropic_model,
                max_tokens=8000,
                system=SYSTEM,
                messages=[{"role": "user", "content": USER_TMPL.format(context=json.dumps(context, indent=1))}],
                output_format=Suggestions,
                output_config={"effort": "low"},
            )
        except anthropic.AuthenticationError:
            raise SuggestError("Claude rejected the API key. Check ANTHROPIC_API_KEY.", 502) from None
        except anthropic.RateLimitError:
            raise SuggestError("Claude rate limit reached — try again in a minute.", 429) from None
        except anthropic.APIConnectionError:
            raise SuggestError("Could not reach the Claude API. Check your connection.", 502) from None
        except anthropic.APIStatusError as e:
            raise SuggestError(f"Claude API error ({e.status_code}): {e.message[:160]}", 502) from None

        parsed = resp.parsed_output
        if parsed is None or not parsed.setups:
            why = "the response was cut off" if resp.stop_reason == "max_tokens" else "no valid structured answer was returned"
            raise SuggestError(f"Claude did not produce usable setups ({why}). Try Refresh.", 502)

        payload = parsed.model_dump()
        try:
            store.insert("suggestions", {"symbol": u.symbol, "model": s.anthropic_model, "context_json": context, "setups_json": payload})
        except Exception:  # noqa: BLE001 - caching is best-effort; never lose a paid-for answer
            pass
        return {**payload, "context": context, "generated_at": utc_now_iso(), "model": s.anthropic_model, "cached": False}
