"""Thin synchronous Upstox REST client (only the endpoints Axiom needs).

Endpoint shapes were checked against Upstox's published API docs (v3 order placement on the
api-hft host, v3 historical/intraday candles, v2 option chain / contracts, v2 order book,
short-term positions, market status). Reads are retried on transient failures; order-mutating
calls are NEVER auto-retried (a retry after a timeout could double-place an order).
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, Callable
from urllib.parse import quote

import httpx
import pandas as pd

from bot.auth import AuthRequired, get_access_token
from core.config import DATA_DIR
from core.timeutil import IST, today_ist

BASE = "https://api.upstox.com"
HFT = "https://api-hft.upstox.com"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

_RETRY_STATUS = {429, 502, 503, 504}


class UpstoxError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"Upstox {status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class UpstoxAuthError(UpstoxError):
    pass


def _enc(key: str) -> str:
    return quote(key, safe="")


def candles_to_df(raw: list[list[Any]]) -> pd.DataFrame:
    """Upstox candle rows: [ts, open, high, low, close, volume, oi] -> ascending IST-indexed frame."""
    cols = ["ts", "open", "high", "low", "close", "volume", "oi"]
    if not raw:
        return pd.DataFrame(columns=cols[1:], index=pd.DatetimeIndex([], tz=IST, name="ts"))
    df = pd.DataFrame(raw, columns=cols[: len(raw[0])])
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(IST)
    df = df.drop_duplicates("ts").sort_values("ts").set_index("ts")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "oi" not in df:
        df["oi"] = 0.0
    return df[["open", "high", "low", "close", "volume", "oi"]]


class UpstoxClient:
    def __init__(self, token_provider: Callable[[], str] = get_access_token, timeout: float = 15.0):
        self._token = token_provider
        self._http = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ plumbing
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Authorization": f"Bearer {self._token()}"}

    def _parse(self, r: httpx.Response) -> dict:
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400 or body.get("status") == "error":
            errs = body.get("errors") or [{}]
            e0 = errs[0] if errs else {}
            code = e0.get("errorCode") or e0.get("error_code") or ""
            msg = e0.get("message") or r.text[:200]
            cls = UpstoxAuthError if r.status_code in (401, 403) else UpstoxError
            raise cls(r.status_code, code, msg)
        return body

    def _get(self, url: str, params: dict | None = None) -> dict:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self._http.get(url, params=params, headers=self._headers())
                if r.status_code in _RETRY_STATUS and attempt < 2:
                    time.sleep(0.5 * (3**attempt))
                    continue
                return self._parse(r)
            except httpx.TransportError as e:
                last = e
                time.sleep(0.5 * (3**attempt))
        raise UpstoxError(0, "NETWORK", f"network error talking to Upstox: {last}")

    # ------------------------------------------------------------------ market data
    def ltp(self, keys: list[str]) -> dict[str, float]:
        """Last traded price per instrument key. Response key format varies, so map via instrument_token."""
        if not keys:
            return {}
        body = self._get(f"{BASE}/v3/market-quote/ltp", {"instrument_key": ",".join(keys)})
        out: dict[str, float] = {}
        for k, v in (body.get("data") or {}).items():
            if not isinstance(v, dict) or v.get("last_price") is None:
                continue
            key = v.get("instrument_token") or k.replace(":", "|", 1)
            out[key] = float(v["last_price"])
        return out

    def intraday_candles(self, key: str, interval: int, unit: str = "minutes") -> pd.DataFrame:
        body = self._get(f"{BASE}/v3/historical-candle/intraday/{_enc(key)}/{unit}/{interval}")
        return candles_to_df((body.get("data") or {}).get("candles") or [])

    def historical_candles(self, key: str, interval: int, start: date, end: date, unit: str = "minutes") -> pd.DataFrame:
        body = self._get(
            f"{BASE}/v3/historical-candle/{_enc(key)}/{unit}/{interval}/{end.isoformat()}/{start.isoformat()}"
        )
        return candles_to_df((body.get("data") or {}).get("candles") or [])

    def candles_range(self, key: str, interval: int, start: date, end: date, unit: str = "minutes") -> pd.DataFrame:
        """Historical candles over an arbitrary range, chunked to Upstox's per-request limits and
        cached on disk for chunks that are fully in the past."""
        if unit == "minutes":
            span = 27 if interval <= 15 else 85
        elif unit == "hours":
            span = 85
        else:
            span = 3000
        frames: list[pd.DataFrame] = []
        cur = start
        today = today_ist()
        safe = key.replace("|", "_").replace(" ", "")
        while cur <= end:
            chunk_end = min(cur + timedelta(days=span), end)
            cache = CACHE_DIR / f"{safe}_{unit}{interval}_{cur}_{chunk_end}.csv"
            if chunk_end < today and cache.exists():
                df = pd.read_csv(cache, index_col=0)
                df.index = pd.to_datetime(df.index, utc=True).tz_convert(IST)
                df.index.name = "ts"
            else:
                df = self.historical_candles(key, interval, cur, chunk_end, unit)
                if chunk_end < today and len(df):
                    df.to_csv(cache)
            frames.append(df)
            cur = chunk_end + timedelta(days=1)
        if not frames:
            return candles_to_df([])
        out = pd.concat(frames)
        return out[~out.index.duplicated(keep="last")].sort_index()

    # ------------------------------------------------------------------ options
    def option_contracts(self, underlying_key: str, expiry: str | None = None) -> list[dict]:
        params = {"instrument_key": underlying_key}
        if expiry:
            params["expiry_date"] = expiry
        return self._get(f"{BASE}/v2/option/contract", params).get("data") or []

    def option_chain(self, underlying_key: str, expiry: str) -> list[dict]:
        return self._get(f"{BASE}/v2/option/chain", {"instrument_key": underlying_key, "expiry_date": expiry}).get("data") or []

    # ------------------------------------------------------------------ account
    def positions(self) -> list[dict]:
        return self._get(f"{BASE}/v2/portfolio/short-term-positions").get("data") or []

    def orders(self) -> list[dict]:
        return self._get(f"{BASE}/v2/order/retrieve-all").get("data") or []

    def market_status(self, exchange: str = "NSE") -> str:
        return (self._get(f"{BASE}/v2/market/status/{exchange}").get("data") or {}).get("status", "UNKNOWN")

    def feed_authorize(self) -> str:
        body = self._get(f"{BASE}/v3/feed/market-data-feed/authorize")
        uri = (body.get("data") or {}).get("authorized_redirect_uri")
        if not uri:
            raise UpstoxError(0, "FEED", "no authorized_redirect_uri in response")
        return uri

    # ------------------------------------------------------------------ orders (never retried)
    def _order_headers(self, algo_name: str = "") -> dict[str, str]:
        h = {**self._headers(), "Content-Type": "application/json"}
        if algo_name:
            h["X-Algo-Name"] = algo_name
        return h

    def place_order(self, body: dict, algo_name: str = "") -> list[str]:
        r = self._http.post(f"{HFT}/v3/order/place", json=body, headers=self._order_headers(algo_name))
        data = self._parse(r).get("data") or {}
        return list(data.get("order_ids") or [])

    def modify_order(self, body: dict, algo_name: str = "") -> str:
        r = self._http.put(f"{HFT}/v3/order/modify", json=body, headers=self._order_headers(algo_name))
        return str((self._parse(r).get("data") or {}).get("order_id", body.get("order_id", "")))

    def cancel_order(self, order_id: str, algo_name: str = "") -> str:
        r = self._http.delete(f"{HFT}/v3/order/cancel", params={"order_id": order_id}, headers=self._order_headers(algo_name))
        return str((self._parse(r).get("data") or {}).get("order_id", order_id))


__all__ = ["UpstoxClient", "UpstoxError", "UpstoxAuthError", "AuthRequired", "candles_to_df"]
