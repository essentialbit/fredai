"""Broad Dollar Index (FRED DTWEXBGS) -- currency-market macro regime badge.

DTWEXBGS is the Fed's Nominal Broad U.S. Dollar Index (trade-weighted vs. a
broad basket of currencies). Every macro badge shipped or queued so far reads
equities options-implied vol (VIX/SKEW), commodities (copper/gold), corporate
credit (HYG/LQD), or rates -- none track the currency market itself, one of
the primary channels macro regime shifts propagate through (a strengthening
broad dollar tightens financial conditions for commodity exporters and
emerging-market borrowers; a weakening one eases them).

Same free fredgraph.csv fetch already used for breakeven inflation / jobless
claims (no API key, no signup) and the same z-score-lite trend shape as
copper_gold_ratio.py's _trend() helper, reused here for consistency across
macro-strip badges.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS"
_CACHE_TTL_S = 3600  # DTWEXBGS updates daily on business days; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/breakeven_inflation.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "strengthening"
    elif z < -0.5:
        direction = "weakening"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[DollarIndex] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[DollarIndex] fetch error: {e}")
        return None

    out = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out.append((date, float(raw)))
        except ValueError:
            continue  # FRED uses "." for missing observations (holidays/weekends)
    return out or None


def compute_dollar_index() -> dict | None:
    """{"latest": float, "date": str, "change_wow": float, "trend_20d": {...},
    "regime": "strengthening"/"weakening"/"stable"} or None if the feed can't
    be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    trend_20d = _trend(values[-21:])
    if trend_20d is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    return {
        "latest": latest_val,
        "date": latest_date,
        "change_wow": round(latest_val - prev_val, 2),
        "trend_20d": trend_20d,
        "regime": trend_20d["direction"],
    }


def get_dollar_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_dollar_index()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
