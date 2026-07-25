"""U-6 Broader Unemployment Rate (FRED U6RATE) -- underemployment macro
badge.

U6RATE is the BLS's broadest official unemployment measure: total
unemployed plus marginally attached workers plus those employed part-time
for economic reasons, as a percent of the civilian labor force plus
marginally attached workers. Structurally distinct from the already-shipped
headline U-3 rate (unemployment_rate_client.py, UNRATE): U-6 captures
labor-market slack and underemployment that U-3 misses, and the two series
can diverge meaningfully during recoveries (U-6 stays elevated longer after
a downturn even as U-3 normalizes).

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=U6RATE"
_CACHE_TTL_S = 3600  # U6RATE updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as unemployment_rate_client.py's _trend() -- a rising rate is
    a weakening labor market, a falling rate is an improving one."""
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


def compute_u6_unemployment() -> dict | None:
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


def get_u6_unemployment(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_u6_unemployment()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
