"""Live prices over Upstox's market-data WebSocket (v3, protobuf).

Design notes
  * Runs in its own thread with its own asyncio loop; the bot just calls `get(key)`.
  * The authorised wss:// URI is single-use, so every (re)connect fetches a fresh one first.
  * TLS is verified (the Upstox SDK's own feeder disables certificate checks; we only borrow its
    generated protobuf decoder).
  * Reconnects with capped exponential backoff. If ticks are missing/stale the bot transparently
    falls back to REST LTP polling, so a dead socket degrades latency instead of stopping risk checks.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

from google.protobuf.json_format import MessageToDict
from websockets.asyncio.client import connect

from bot.logger import BotLogger
from core.upstox import UpstoxClient

try:  # official generated decoder shipped with the Upstox SDK
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb
except Exception:  # noqa: BLE001 - feed is optional; REST polling still works
    pb = None


def extract_ltps(message: dict) -> dict[str, float]:
    """Pull {instrument_key: ltp} out of a decoded FeedResponse dict (handles ltpc/full/index feeds)."""
    out: dict[str, float] = {}
    for key, feed in (message.get("feeds") or {}).items():
        full = feed.get("fullFeed") or {}
        ltpc = (
            feed.get("ltpc")
            or (full.get("marketFF") or {}).get("ltpc")
            or (full.get("indexFF") or {}).get("ltpc")
            or {}
        )
        ltp = ltpc.get("ltp")
        if ltp is not None:
            out[key] = float(ltp)
    return out


class LiveFeed:
    def __init__(self, client: UpstoxClient, log: BotLogger | None = None):
        self.client, self.log = client, log
        self._ltp: dict[str, tuple[float, float]] = {}  # key -> (price, monotonic time)
        self._wanted: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self.connected = False
        self.last_error = ""

    # ------------------------------------------------------------------ control
    def start(self, keys: list[str]) -> None:
        if pb is None:
            self._note("protobuf decoder unavailable; using REST polling only")
            return
        with self._lock:
            self._wanted.update(keys)
        self._thread = threading.Thread(target=self._thread_main, name="upstox-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def subscribe(self, keys: list[str]) -> None:
        with self._lock:
            new = [k for k in keys if k not in self._wanted]
            self._wanted.update(keys)
        if new and self.connected and self._loop:
            asyncio.run_coroutine_threadsafe(self._send("sub", new), self._loop)

    def unsubscribe(self, keys: list[str]) -> None:
        with self._lock:
            gone = [k for k in keys if k in self._wanted]
            self._wanted.difference_update(keys)
        if gone and self.connected and self._loop:
            asyncio.run_coroutine_threadsafe(self._send("unsub", gone), self._loop)

    def get(self, key: str, max_age: float = 5.0) -> float | None:
        with self._lock:
            hit = self._ltp.get(key)
        if hit and time.monotonic() - hit[1] <= max_age:
            return hit[0]
        return None

    # ------------------------------------------------------------------ internals
    def _note(self, msg: str) -> None:
        self.last_error = msg
        if self.log:
            self.log.warn(f"feed: {msg}")

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._forever())

    async def _forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1.0
            except Exception as e:  # noqa: BLE001 - any failure -> reconnect
                self._note(f"disconnected: {type(e).__name__}: {str(e)[:160]}")
            self.connected = False
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _session(self) -> None:
        loop = asyncio.get_running_loop()
        uri = await loop.run_in_executor(None, self.client.feed_authorize)
        async with connect(uri, max_size=None, ping_interval=20, open_timeout=15) as ws:
            self._ws, self.connected, self.last_error = ws, True, ""
            if self.log:
                self.log.info("feed: connected")
            with self._lock:
                wanted = list(self._wanted)
            if wanted:
                await self._send("sub", wanted)
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    self._on_message(bytes(raw))

    async def _send(self, method: str, keys: list[str]) -> None:
        if not self._ws:
            return
        req = {"guid": uuid.uuid4().hex[:20], "method": method, "data": {"mode": "ltpc", "instrumentKeys": keys}}
        if method == "unsub":
            req["data"].pop("mode")
        await self._ws.send(json.dumps(req).encode())  # must be a binary frame

    def _on_message(self, raw: bytes) -> None:
        try:
            msg = MessageToDict(pb.FeedResponse.FromString(raw))
        except Exception as e:  # noqa: BLE001 - one bad frame must not kill the feed
            self._note(f"undecodable frame: {e}")
            return
        ticks = extract_ltps(msg)
        if ticks:
            now = time.monotonic()
            with self._lock:
                for k, v in ticks.items():
                    self._ltp[k] = (v, now)
