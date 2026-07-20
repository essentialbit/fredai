"""Core CPI YoY Inflation (FRED CPILFESL) -- ex food/energy Consumer Price
Index, the Fed and markets' primary underlying-inflation read.

Fred already has headline CPI (CPIAUCSL, includes volatile food/energy) and
Core PCE (PCEPILFE, the Fed's official inflation-target gauge, different
BLS-vs-BEA basket/weighting methodology). CPILFESL is neither of those: it's
the BLS's own ex-food-energy series, and the number most commonly cited
alongside headline CPI in market commentary as "core inflation."

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.

CPILFESL is a price *index level*, not a growth rate, and levels trend
monotonically upward over any long window -- a z-score on the raw level
would always read "rising" and say nothing useful. Convert to
year-over-year percent change first, then trend that (same pattern as
cpi_client.py/core_pce_client.py).
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPILFESL"
_CACHE_TTL_S = 3600  # CPILFESL updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as cpi_client.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "accelerating"
    elif z < -0.5:
        direction = "decelerating"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[CoreCPI] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[CoreCPI] fetch error: {e}")
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


def compute_core_cpi() -> dict | None:
    """{"latest": float, "date": str, "yoy_pct": float, "trend_12m": {...},
    "regime": "accelerating"/"decelerating"/"stable"} or None if the feed
    can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 14:
        return None

    yoy_series = []
    for i in range(12, len(series)):
        year_ago_val = series[i - 12][1]
        if year_ago_val:
            yoy_series.append((series[i][0], (series[i][1] - year_ago_val) / year_ago_val * 100))

    if len(yoy_series) < 13:
        return None

    values = [v for _, v in yoy_series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_yoy = yoy_series[-1]

    return {
        "latest": round(series[-1][1], 2),
        "date": latest_date,
        "yoy_pct": round(latest_yoy, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_core_cpi(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_core_cpi()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
