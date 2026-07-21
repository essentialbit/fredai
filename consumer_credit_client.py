"""Total Consumer Credit Outstanding (FRED TOTALSL) -- household-leverage
macro badge.

Every prior macro badge covers labor, inflation, output, capex, trade, or
housing -- household balance-sheet leverage/deleveraging is uncovered.
TOTALSL (revolving + non-revolving consumer credit, seasonally adjusted,
monthly) is the standard aggregate consumer-credit stock, a leading
indicator of consumer spending capacity and over-extension risk.

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TOTALSL"
_CACHE_TTL_S = 3600  # TOTALSL updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "expanding"
    elif z < -0.5:
        direction = "decelerating"
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


def compute_consumer_credit() -> dict | None:
    """{"latest_billions": float, "yoy_change_pct": float, "trend_12m": {...},
    "regime"} (regime is "expanding"/"decelerating"/"stable", derived from
    the trailing-12-month rolling z-score direction), or None if the FRED
    fetch fails or there isn't enough history yet."""
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

    yoy_start = series[-13]
    yoy_change_pct = (series[-1] - yoy_start) / yoy_start * 100 if yoy_start else None

    return {
        "latest_billions": round(series[-1], 1),
        "yoy_change_pct": round(yoy_change_pct, 2) if yoy_change_pct is not None else None,
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_consumer_credit(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_consumer_credit()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
