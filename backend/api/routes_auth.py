from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from bot import auth
from core import activity
from core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _back(ok: bool, reason: str = "") -> RedirectResponse:
    q = urlencode({"auth": "ok" if ok else "error", **({"reason": reason} if reason else {})})
    return RedirectResponse(f"{get_settings().frontend_url.rstrip('/')}/bot?{q}", status_code=302)


@router.get("/status")
def auth_status() -> dict:
    return auth.status()


@router.get("/login")
def login():
    """Browser navigates here; we bounce to Upstox's login dialog."""
    try:
        url = auth.build_login_url()
    except auth.AuthRequired as e:
        activity.record("auth", "login_failed", f"Couldn't start the Upstox login: {e}", level="WARN")
        return _back(False, str(e))
    activity.record("auth", "login_start", "Started the Upstox login")
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = Query(None), error_description: str | None = None):
    """Upstox redirects here (this URL must equal the redirect URI registered in your Upstox app)."""
    # Nothing from the callback's query string (code, state) is ever logged.
    if error or not code:
        reason = error_description or error or "Login was cancelled"
        activity.record("auth", "login_failed", f"Upstox login not completed: {reason}", level="WARN")
        return _back(False, reason)
    if not auth.consume_state(state):
        activity.record("auth", "login_failed", "Upstox login rejected: state mismatch (stale or forged callback)", level="WARN")
        return _back(False, "Login state mismatch — start the login again from the app")
    try:
        auth.exchange_code(code)
    except auth.AuthRequired as e:
        activity.record("auth", "login_failed", f"Upstox login failed: {e}", level="ERROR")
        return _back(False, str(e))
    activity.record("auth", "login", "Upstox connected")
    return _back(True)


@router.post("/logout")
def logout() -> dict:
    auth.clear_token()
    activity.record("auth", "logout", "Disconnected from Upstox")
    return {"ok": True}
