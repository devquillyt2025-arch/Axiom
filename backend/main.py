"""Axiom API.  Run:  uvicorn main:app --host 127.0.0.1 --port 8000   (from backend/)"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from api import botctl, routes_auth, routes_bot, routes_data, routes_logs, routes_market
from bot.auth import AuthRequired
from core import activity
from core.config import get_settings
from core.store import StoreError, get_store
from core.suggest import SuggestError
from core.upstox import UpstoxAuthError, UpstoxError

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    store = get_store().kind
    mode = "paper" if settings.paper_trade else "LIVE"
    activity.record("system", "api_start", f"Axiom API started · {store} store · default mode {mode}", details={"store": store, "paper_trade": settings.paper_trade})
    yield


app = FastAPI(title="Axiom API", version="1.0.0", lifespan=lifespan)

# --- the API can place real orders, so lock it to the local frontend -------------------------
allowed_hosts = ["localhost", "127.0.0.1"] + (["testserver"] if os.getenv("AXIOM_TESTING") else [])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)  # blocks DNS-rebinding
CSRF_HEADER = "x-axiom"


@app.middleware("http")
async def require_custom_header(request: Request, call_next):
    """State-changing calls must carry X-Axiom. Browsers only allow custom headers cross-origin
    after a CORS preflight, which we grant to the frontend origin alone — so other sites can't POST."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and CSRF_HEADER not in request.headers:
        return JSONResponse({"detail": "Missing X-Axiom header"}, status_code=403)
    return await call_next(request)


app.add_middleware(  # added last => outermost, so preflights are answered before the header check
    CORSMiddleware,
    allow_origins=sorted({settings.frontend_url.rstrip("/"), "http://localhost:3000", "http://127.0.0.1:3000"}),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Axiom"],
)

for r in (routes_auth.router, routes_bot.router, routes_market.router, routes_data.router, routes_logs.router):
    app.include_router(r)


# --- errors -> clean JSON ----------------------------------------------------------------------
def _err(request: Request, status: int, msg: str, **extra) -> JSONResponse:
    path = request.url.path
    if not activity.is_quiet(path):  # polled endpoints would repeat the same error forever
        activity.record(
            activity.category_for(path), "error", f"{request.method} {path} → {status}: {msg}",
            level="ERROR" if status >= 500 else "WARN", details={"status": status, **extra}, dedupe_s=30,
        )
    return JSONResponse({"detail": msg, **extra}, status_code=status)


@app.exception_handler(AuthRequired)
async def _auth(request: Request, e: AuthRequired):
    return _err(request, 401, str(e), code="auth_required")


@app.exception_handler(UpstoxAuthError)
async def _upstox_auth(request: Request, e: UpstoxAuthError):
    return _err(request, 401, "Upstox rejected the session — log in again.", code="auth_required")


@app.exception_handler(UpstoxError)
async def _upstox(request: Request, e: UpstoxError):
    return _err(request, 502, e.message or str(e), code="upstox_error")


@app.exception_handler(SuggestError)
async def _suggest(request: Request, e: SuggestError):
    return _err(request, e.status, str(e))


@app.exception_handler(StoreError)
async def _store(request: Request, e: StoreError):
    return _err(request, 503, str(e), code="store_error")


@app.exception_handler(botctl.Conflict)
async def _conflict(request: Request, e: botctl.Conflict):
    return _err(request, 409, str(e))


@app.exception_handler(ValueError)
async def _value(request: Request, e: ValueError):
    return _err(request, 400, str(e))


@app.exception_handler(LookupError)
async def _lookup(request: Request, e: LookupError):
    return _err(request, 404, str(e))


@app.get("/health")
def health() -> dict:
    ok, detail = get_store().healthcheck()
    return {"api": "ok", "store": get_store().kind, "store_ok": ok, "store_detail": detail}
