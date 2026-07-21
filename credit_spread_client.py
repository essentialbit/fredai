"""Moody's Baa Corporate Yield Spread (BAA10Y) -- investment-grade credit
stress macro badge.

BAA10Y (Moody's Seasoned Baa Corporate Bond Yield minus the 10-Year
Treasury Constant Maturity Rate) is the standard investment-grade credit
risk premium: a widening spread reads rising corporate credit stress /
tightening financial conditions, a narrowing spread reads market
confidence / easy financial conditions. Distinct from the already-shipped
high-yield-vs-investment-grade ETF price ratio (HYG/LQD relative
performance) and the ICE BofA option-adjusted spread (OAS) badges -- this
is the specific investment-grade cash-bond spread the Fed's own credit
conditions commentary most often cites.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (jobless claims, breakeven inflation, industrial
production, Core PCE) -- never curl, see the documented HTTP/2 gotcha in
project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y"
_CACHE_TTL_S = 3600  # BAA10Y updates daily on business days; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as core_pce_client.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "widening"
    elif z < -0.5:
        direction = "narrowing"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[CreditSpread] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[CreditSpread] fetch error: {e}")
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


def compute_credit_spread() -> dict | None:
    """{"latest": float, "date": str, "change_20d_bps": float,
    "trend_20d": {...}, "regime": "widening"/"narrowing"/"stable"} or None
    if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    window = values[-21:]
    trend_20d = _trend(window)
    if trend_20d is None:
        return None

    latest_date, latest_val = series[-1]
    change_20d_bps = round((window[-1] - window[0]) * 100, 1)

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_20d_bps": change_20d_bps,
        "trend_20d": trend_20d,
        "regime": trend_20d["direction"],
    }


def get_credit_spread(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_credit_spread()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
