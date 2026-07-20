"""10-Year Breakeven Inflation Rate (FRED T10YIE) -- market-implied inflation
expectation macro badge.

T10YIE = nominal 10Y Treasury yield minus 10Y TIPS real yield, i.e. what the
bond market is pricing in for average inflation over the next decade. Distinct
from the yield-curve (nominal term structure) and credit-spread (corporate
default-risk premium) signals already shipped -- this is a direct read on
inflation expectations, one of the Phase 2 macro-regime taxonomy's inputs
agreed on issue #103 (Goldilocks / Inflationary Boom / Stagflation Risk /
Deflationary Bust / Transition).

Same free fredgraph.csv fetch already used for jobless claims (no API key,
no signup) and the same z-score-lite trend shape as copper_gold_ratio.py's
_trend() helper, reused here for consistency across macro-strip badges.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10YIE"
_CACHE_TTL_S = 3600  # T10YIE updates daily on business days; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/jobless_claims_client.py's _trend()."""
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
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[BreakevenInflation] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[BreakevenInflation] fetch error: {e}")
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


def compute_breakeven_inflation() -> dict | None:
    """{"latest": float, "date": str, "change_wow": float, "trend_20d": {...},
    "regime": "rising"/"falling"/"stable"} or None if the feed can't be
    fetched or has too little history."""
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


def get_breakeven_inflation(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_breakeven_inflation()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
