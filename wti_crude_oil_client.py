"""WTI Crude Oil Spot Price (FRED DCOILWTICO) -- energy-price macro badge.

DCOILWTICO tracks the daily Cushing, OK WTI spot price -- the headline
energy-inflation input that feeds directly into CPI/PPI energy components,
transport costs, and corporate input costs. Distinct from the already-shipped
commodity futures curve (contango/backwardation *shape*, not level) and the
Oil & Gas Extraction Industrial Production Index (physical production
*volume*, not price) -- this is the outright spot price level.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge -- never curl, see the documented HTTP/2 gotcha in
project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"
_CACHE_TTL_S = 3600  # DCOILWTICO updates daily; hourly refetch is plenty


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
            print(f"[WtiCrudeOil] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[WtiCrudeOil] fetch error: {e}")
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


def compute_wti_crude_oil() -> dict | None:
    """{"latest": float (USD/bbl), "date": str, "change_d1_pct": float,
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


def get_wti_crude_oil(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_wti_crude_oil()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
