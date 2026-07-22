"""Headline PCE Price Index (PCEPI) macro badge.

PCEPI is the specific series the Fed's 2% inflation objective is defined
against in official FOMC communications -- distinct from every inflation
badge already shipped: Core PCE (PCEPILFE, core_pce_client.py) excludes
food and energy while this tracks the full basket; headline CPI
(CPIAUCSL, cpi_client.py) uses a different survey methodology and
weighting scheme (BLS urban-consumer basket vs. BEA chain-weighted
expenditure basket) and runs persistently above PCE readings; the T10YIE
badge tracks market-implied breakeven expectations, not a realized print.

Same free fredgraph.csv fetch pattern as every other FRED-sourced badge --
never curl, see the documented HTTP/2 gotcha in project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPI"
_CACHE_TTL_S = 3600  # PCEPI updates monthly; hourly refetch is plenty
_FED_TARGET_YOY_PCT = 2.0
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
        direction = "accelerating"
    elif z < -0.5:
        direction = "decelerating"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[PCEPriceIndex] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[PCEPriceIndex] fetch error: {e}")
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


def compute_pce_price_index() -> dict | None:
    """{"latest": float, "date": str, "yoy_pct": float,
    "vs_fed_target_pct": float, "trend_12m": {...},
    "regime": "accelerating"/"decelerating"/"stable"} or None if the feed
    can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 14:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]
    year_ago_val = series[-13][1]
    yoy_pct = (latest_val - year_ago_val) / year_ago_val * 100 if year_ago_val else None
    if yoy_pct is None:
        return None

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "yoy_pct": round(yoy_pct, 2),
        "vs_fed_target_pct": round(yoy_pct - _FED_TARGET_YOY_PCT, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_pce_price_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_pce_price_index()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
