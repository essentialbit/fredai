"""Real Interest Rate (FRED DFII10, 10-Year TIPS yield) -- macro badge.

DFII10 is the daily market-yield on 10-Year Treasury Inflation-Protected
Securities -- the real (inflation-adjusted) interest rate. Rising real
yields tighten financial conditions and compress equity/growth-asset
valuations independent of nominal rates or inflation expectations, closing
the third leg of the rates triangle alongside the already-shipped nominal
yield-curve-shape (2s10s) and breakeven-inflation-expectations badges.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge -- never curl, see the documented HTTP/2 gotcha in
project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
_CACHE_TTL_S = 3600  # DFII10 updates daily; hourly refetch is plenty


_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's _trend()."""
    if len(series) < 20:
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
            print(f"[RealInterestRate] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[RealInterestRate] fetch error: {e}")
        return None

    out = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out.append((date, float(raw)))
        except ValueError:
            continue  # FRED uses "." for missing observations (weekends/holidays)
    return out or None


def compute_real_interest_rate() -> dict | None:
    """{"latest": float (percent), "date": str, "change_d1_pct": float,
    "trend_60d": {...}, "regime": "rising"/"falling"/"stable"} or
    None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 61:
        return None

    values = [v for _, v in series]
    trend_60d = _trend(values[-60:])
    if trend_60d is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_d1_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None

    return {
        "latest": round(latest_val, 2),
        "date": latest_date,
        "change_d1_pct": round(change_d1_pct, 2) if change_d1_pct is not None else None,
        "trend_60d": trend_60d,
        "regime": trend_60d["direction"],
    }


def get_real_interest_rate(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_real_interest_rate()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
