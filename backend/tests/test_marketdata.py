"""Regression tests for the payload the chart consumes."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd
import pytest

from core import marketdata
from core.timeutil import IST


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_chart_times_are_epoch_seconds_at_any_datetime_resolution(unit):
    # pandas 3 can hold datetimes at µs resolution; the old `astype('int64') // 10**9` broke on that.
    start = datetime(2026, 10, 14, 9, 15, tzinfo=IST)
    idx = pd.DatetimeIndex([start + timedelta(minutes=5 * i) for i in range(5)]).as_unit(unit)
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}, index=idx)
    bars = marketdata._to_bars(df)
    times = [b["time"] for b in bars]
    assert times == sorted(set(times)), "times must be strictly increasing (the chart library rejects duplicates)"
    assert times[1] - times[0] == 300
    expected = int(start.timestamp()) + marketdata.IST_OFFSET_S
    assert times[0] == expected


def test_live_snapshot_candle_times_are_sane_and_unique():
    snap = marketdata.live_snapshot("NIFTY", interval=5, days=3)  # demo data (no token in tests)
    times = [c["time"] for c in snap["candles"]]
    assert len(times) == len(set(times)) > 50
    assert times == sorted(times)
    now = time.time()
    assert now - 15 * 86400 < times[-1] - marketdata.IST_OFFSET_S < now + 86400
