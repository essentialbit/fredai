"""Velocity of M2 Money Stock (FRED M2V) -- quarterly monetary-dynamics
macro badge.

M2V (GDP / M2, quarterly) measures how fast money circulates through the
economy. Distinct from the already-shipped M2 level badge (fed_liquidity.py
tracks WALCL/M2SL levels -- how much money exists, not how fast it moves):
falling velocity means money is sitting idle (deflationary/liquidity-trap
risk), rising velocity means faster circulation (inflationary pressure
building). Central banks watch this alongside the level itself, making it a
genuinely new leg in the monetary-conditions category rather than a
duplicate of the level badge.

M2V is already a ratio (not a monotonically-increasing index level), so it
trends directly like copper_gold_ratio.py's ratio series -- no YoY/growth
transform needed, unlike level-index series (ECIALLCIV, GDPC1).

Same free, keyless fredgraph.csv fetch pattern already proven for every
other FRED-sourced badge -- never curl, see the documented HTTP/2
stream-reset gotcha in project memory; plain requests.get matches every
shipped FRED client's real code path.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2V"
_CACHE_TTL_S = 21600  # M2V updates quarterly; 6h refetch is plenty

_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as eci_client.py's/copper_gold_ratio.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[M2Velocity] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[M2Velocity] fetch error: {e}")
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


def compute_m2_velocity() -> dict | None:
    """{"latest": float, "date": str, "trend_20q": {...} (z-scored against a
    trailing 20-quarter/5-year window), "regime": "rising"/"falling"/"stable"}
    or None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    dates = [d for d, _ in series]
    values = [v for _, v in series]

    window = values[-21:]
    trend_20q = _trend(window)
    if trend_20q is None:
        return None

    return {
        "latest": round(values[-1], 3),
        "date": dates[-1],
        "trend_20q": trend_20q,
        "regime": trend_20q["direction"],
    }


def get_m2_velocity(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_m2_velocity()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
