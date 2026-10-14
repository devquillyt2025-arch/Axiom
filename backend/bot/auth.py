"""Upstox OAuth 2.0 (authorization-code flow) + token lifecycle.

Important: Upstox access tokens expire at 03:30 IST the next day and Upstox does NOT issue a
refresh token for this flow. So "refresh" here means: detect expiry early, report it clearly,
and send the user through the login flow again (one click on the "Connect Upstox" button).
Never automate the login with your PIN/TOTP secrets in this app — we deliberately don't store them.
"""
from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlencode

import httpx

from core.config import DATA_DIR, get_settings
from core.timeutil import next_token_expiry, now_ist, to_ist

AUTH_DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

TOKEN_FILE = DATA_DIR / "token.json"
_lock = threading.Lock()
_pending_states: dict[str, float] = {}  # OAuth `state` values we issued -> unix time


class AuthRequired(Exception):
    """No valid Upstox access token. The user must (re)connect."""


@dataclass
class Token:
    access_token: str
    expires_at: str  # ISO, IST
    user_id: str = ""
    user_name: str = ""
    email: str = ""
    broker: str = ""
    issued_at: str = ""
    source: str = "oauth"  # oauth | env

    @property
    def expires_dt(self) -> datetime:
        return to_ist(datetime.fromisoformat(self.expires_at))

    def seconds_left(self) -> float:
        return (self.expires_dt - now_ist()).total_seconds()

    @property
    def valid(self) -> bool:
        return bool(self.access_token) and self.seconds_left() > 60


def _configured() -> None:
    s = get_settings()
    if not (s.upstox_api_key and s.upstox_api_secret and s.upstox_redirect_uri):
        raise AuthRequired(
            "UPSTOX_API_KEY / UPSTOX_API_SECRET / UPSTOX_REDIRECT_URI are not set. Copy .env.example to .env and fill them in."
        )


def build_login_url() -> str:
    _configured()
    s = get_settings()
    state = secrets.token_urlsafe(24)
    with _lock:
        # keep the table tiny; a login takes seconds
        now = datetime.now().timestamp()
        for k in [k for k, t in _pending_states.items() if now - t > 900]:
            _pending_states.pop(k, None)
        _pending_states[state] = now
    q = urlencode(
        {"client_id": s.upstox_api_key, "redirect_uri": s.upstox_redirect_uri, "response_type": "code", "state": state}
    )
    return f"{AUTH_DIALOG_URL}?{q}"


def consume_state(state: str | None) -> bool:
    """CSRF check for the callback: the state must be one we issued, and is single-use."""
    if not state:
        return False
    with _lock:
        return _pending_states.pop(state, None) is not None


def exchange_code(code: str) -> Token:
    _configured()
    s = get_settings()
    resp = httpx.post(
        TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "code": code,
            "client_id": s.upstox_api_key,
            "client_secret": s.upstox_api_secret,
            "redirect_uri": s.upstox_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if resp.status_code != 200:
        # Don't echo the response body blindly into logs — it can contain request details.
        raise AuthRequired(f"Upstox token exchange failed (HTTP {resp.status_code}). The code is single-use; try logging in again.")
    body = resp.json()
    now = now_ist()
    token = Token(
        access_token=body["access_token"],
        expires_at=next_token_expiry(now).isoformat(),
        user_id=body.get("user_id", ""),
        user_name=body.get("user_name", ""),
        email=body.get("email", ""),
        broker=body.get("broker", ""),
        issued_at=now.isoformat(),
        source="oauth",
    )
    save_token(token)
    return token


def save_token(token: Token) -> None:
    with _lock:
        TOKEN_FILE.write_text(json.dumps(asdict(token), indent=2), encoding="utf-8")


def load_token() -> Token | None:
    """Current token or None. Env override wins (useful for scripted/CI runs)."""
    s = get_settings()
    if s.upstox_access_token:
        return Token(
            access_token=s.upstox_access_token,
            expires_at=next_token_expiry(now_ist()).isoformat(),
            source="env",
        )
    with _lock:
        if not TOKEN_FILE.exists():
            return None
        try:
            return Token(**json.loads(TOKEN_FILE.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            return None


def get_access_token() -> str:
    token = load_token()
    if token is None:
        raise AuthRequired("Not connected to Upstox. Click 'Connect Upstox' to log in.")
    if not token.valid:
        raise AuthRequired("Your Upstox session has expired (tokens last until 03:30 IST). Log in again.")
    return token.access_token


def is_authenticated() -> bool:
    t = load_token()
    return bool(t and t.valid)


def clear_token() -> None:
    with _lock:
        TOKEN_FILE.unlink(missing_ok=True)


def status() -> dict:
    t = load_token()
    s = get_settings()
    return {
        "configured": bool(s.upstox_api_key and s.upstox_api_secret),
        "authenticated": bool(t and t.valid),
        "user_name": t.user_name if t else "",
        "user_id": t.user_id if t else "",
        "expires_at": t.expires_at if t else None,
        "expires_in_s": int(t.seconds_left()) if t else None,
        "source": t.source if t else None,
    }
