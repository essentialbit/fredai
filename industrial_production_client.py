"""Industrial Production Index (INDPRO) -- real-economy hard-data
manufacturing/output macro badge.

INDPRO is the Fed's monthly index of physical output for the manufacturing,
mining, and utilities sectors (2017=100). Distinct from every other shipped
macro badge: those track financial conditions (NFCI, credit spreads, VIX
term structure) or survey/sentiment (EPU, UMCSENT), while this tracks actual
production volume -- a hard-data confirmation/divergence check against the
softer indicators.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (jobless claims, breakeven inflation, Fed balance
sheet/M2) -- never curl, see the documented HTTP/2 gotcha in project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDPRO"
_CACHE_TTL_S = 3600  # INDPRO updates monthly; hourly refetch is plenty
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
        direction = "contracting"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[IndustrialProduction] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[IndustrialProduction] fetch error: {e}")
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


def compute_industrial_production() -> dict | None:
    """{"latest": float, "date": str, "change_mom_pct": float,
    "trend_12m": {...}, "regime": "expanding"/"contracting"/"stable"} or
    None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_mom_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None
    if change_mom_pct is None:
        return None

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_mom_pct": round(change_mom_pct, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_industrial_production(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_industrial_production()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
