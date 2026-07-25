"""Sahm Rule recession-trigger indicator (real-time labor-market recession
signal, Sahm/Fed definition).

The Sahm Rule is the 3-month moving average of the U.S. unemployment rate
(UNRATE, monthly) minus its own minimum value over the trailing 12 months
of that same 3-month average. A reading at or above 0.50 percentage points
has correctly flagged every U.S. recession since 1970 with no false
positives, so unlike every other macro badge shipped so far this uses a
fixed historical constant for its band, not a rolling z-score -- same
absolute-banding precedent as the EPU index badge (#187/epu_index.py).

Fetched via the same direct fredgraph.csv path already used by
jobless_claims_client.py/breakeven_inflation.py/fed_liquidity.py (plain
requests.get, no special headers -- a bare curl to this endpoint 500s with
an HTTP/2 stream reset, documented project gotcha).
"""
import csv
import io
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE"
_CACHE_TTL_S = 86400  # daily -- UNRATE only updates monthly
_TRIGGER_THRESHOLD = 0.50
_ELEVATED_THRESHOLD = 0.30
_cache: dict = {"computed_at": 0.0, "data": None}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[SahmRule] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[SahmRule] fetch error: {e}")
        return None

    out = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out.append((date, float(raw)))
        except ValueError:
            continue  # FRED uses "." for missing observations
    return out or None


def _three_month_avgs(values: list[float]) -> list[float]:
    """One 3-month trailing average per input point once 3 months are
    available (index i of the output aligns with index i+2 of the input).
    Assumes a contiguous monthly series; a rare BLS release-delay gap in
    UNRATE (confirmed once around 2025-10) would average across the gap
    instead of the missing month, distorting only that historical window,
    not any window computed after data resumes -- same index-based approach
    every sibling FRED-series module (jobless_claims_client.py etc.) uses."""
    return [sum(values[i - 2:i + 1]) / 3 for i in range(2, len(values))]


def compute_sahm_rule() -> dict | None:
    """{"value": float, "date": str, "threemo_avg": float, "trailing_min_12mo": float,
    "regime": "normal"/"elevated"/"recession_signal", "series_12mo": [{"date","value"}, ...]}
    or None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 15:
        return None

    dates = [d for d, _ in series]
    values = [v for _, v in series]
    threemo = _three_month_avgs(values)
    threemo_dates = dates[2:]
    if len(threemo) < 13:
        return None

    latest_avg = threemo[-1]
    trailing_min = min(threemo[-13:])
    sahm_value = round(latest_avg - trailing_min, 2)

    if sahm_value >= _TRIGGER_THRESHOLD:
        regime = "recession_signal"
    elif sahm_value >= _ELEVATED_THRESHOLD:
        regime = "elevated"
    else:
        regime = "normal"

    return {
        "value": sahm_value,
        "date": threemo_dates[-1],
        "threemo_avg": round(latest_avg, 2),
        "trailing_min_12mo": round(trailing_min, 2),
        "regime": regime,
        "series_12mo": [{"date": d, "value": round(v, 2)} for d, v in zip(threemo_dates[-12:], threemo[-12:])],
    }


def get_sahm_rule(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_sahm_rule()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
