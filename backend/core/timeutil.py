"""IST helpers. India has no DST, so a fixed +05:30 offset is exact and needs no tzdata."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
BOT_STOP = time(15, 25)  # bot process stops itself at this time
ENTRY_START = time(9, 20)  # no entries in the first minutes (wide spreads)
ENTRY_CUTOFF = time(14, 45)  # no new entries after this
SQUARE_OFF = time(15, 15)  # every position is flattened at this time

# Upstox access tokens die at 03:30 IST the next day.
TOKEN_EXPIRY = time(3, 30)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def in_market_hours(dt: datetime | None = None) -> bool:
    dt = to_ist(dt or now_ist())
    return is_weekday(dt.date()) and MARKET_OPEN <= dt.time() < MARKET_CLOSE


def next_token_expiry(issued: datetime) -> datetime:
    """The next 03:30 IST strictly after `issued`."""
    issued = to_ist(issued)
    candidate = datetime.combine(issued.date(), TOKEN_EXPIRY, tzinfo=IST)
    if candidate <= issued:
        candidate += timedelta(days=1)
    return candidate


def day_start_utc_iso(d: date | None = None) -> str:
    """ISO UTC timestamp of IST midnight for date `d` (default today) — for 'today' DB filters."""
    d = d or today_ist()
    return datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(timezone.utc).isoformat()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
