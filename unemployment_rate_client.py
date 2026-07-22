"""Civilian Unemployment Rate (FRED UNRATE) -- headline labor-market
macro badge.

The labor-market cluster already covers claims (Initial/Continuing),
JOLTS openings, Payrolls, wage growth, and the derived Sahm Rule
recession trigger -- but not the headline unemployment rate itself, the
single most-cited labor-market number. UNRATE is seasonally adjusted,
monthly.

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE"
_CACHE_TTL_S = 3600  # UNRATE updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as consumer_credit_client.py's _trend(). A rising rate is a
    weakening labor market, a falling rate is an improving one -- opposite
    "good direction" polarity from most macro badges, so regime labels are
    named accordingly rather than reusing the generic rising/falling terms."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "weakening"
    elif z < -0.5:
        direction = "improving"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[float]:
    r = requests.get(_CSV_URL, timeout=15)
    r.raise_for_status()
    reader = csv.reader(io.StringIO(r.text))
    next(reader, None)  # header row
    values = []
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            values.append(float(row[1]))
        except ValueError:
            continue
    return values


def compute_unemployment_rate() -> dict | None:
    """{"latest_pct": float, "change_12m_pts": float, "trend_12m": {...},
    "regime"} (regime is "improving"/"weakening"/"stable", derived from the
    trailing-12-month rolling z-score direction), or None if the FRED fetch
    fails or there isn't enough history yet."""
    try:
        series = _fetch_series()
    except (requests.RequestException, ValueError):
        return None
    if len(series) < 13:
        return None

    window = series[-13:]
    trend_12m = _trend(window)
    if trend_12m is None:
        return None

    change_12m_pts = series[-1] - series[-13]

    return {
        "latest_pct": round(series[-1], 2),
        "change_12m_pts": round(change_12m_pts, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_unemployment_rate(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_unemployment_rate()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
