"""Central settings. Everything comes from environment / .env — nothing is hardcoded."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
# token, bot state, local DB and candle cache live here (gitignored). Overridable for tests.
DATA_DIR = Path(os.getenv("AXIOM_DATA_DIR") or BACKEND_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Upstox ---
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_redirect_uri: str = "http://localhost:8000/auth/callback"
    # Optional: only set if Upstox asks for an algo name on your app (sent as X-Algo-Name).
    upstox_algo_name: str = ""
    # Optional manual override (e.g. a token you generated elsewhere). Normally leave blank
    # and use the in-app "Connect Upstox" OAuth login instead.
    upstox_access_token: str = ""

    # --- Neon Postgres connection string (blank => local SQLite file) ---
    database_url: str = ""

    # --- Claude ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"

    # --- Trading / risk ---
    # Any value pydantic can't parse as a bool raises at startup, so a typo can never
    # silently turn into live trading.
    paper_trade: bool = True
    max_daily_loss: float = Field(default=5000, gt=0)
    max_open_positions: int = Field(default=1, ge=1)
    max_lots: int = Field(default=1, ge=1)  # hard cap on lots per order, whatever the UI asks for
    square_off_on_stop: bool = True
    # Marketable-limit buffer: Upstox no longer accepts plain market orders via API.
    order_price_buffer_pct: float = Field(default=1.0, ge=0, le=10)
    order_fill_timeout_s: int = Field(default=20, ge=3)
    paper_slippage_points: float = Field(default=0.5, ge=0)

    # --- Servers ---
    frontend_url: str = "http://localhost:3000"

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
