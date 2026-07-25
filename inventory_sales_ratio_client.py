"""Total Business Inventories-to-Sales Ratio (FRED ISRATIO) macro-strip badge.

Classic recession-dating leading indicator: tracks whether business
inventories are building up faster than sales (demand/production
imbalance) or staying lean relative to demand. Distinct from every
shipped hard-data activity badge (Industrial Production, Durable Goods,
Retail Sales) -- those measure levels/flows, this measures the *balance*
between production-side stock and demand-side sales.

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.

Unlike the regional-Fed survey badges (diffusion indexes centered near
zero), ISRATIO is a positive-valued ratio (historically ~1.3-1.6) with no
natural zero-crossing, so the trend direction is read off the z-score
alone: a rising ratio means inventories are building relative to the
trailing trend (slowdown risk), a falling ratio means inventories are
lean relative to demand (tightening supply, demand outpacing production).
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=ISRATIO"
_CACHE_TTL_S = 3600  # monthly release; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential)."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "building"
    elif z < -0.5:
        direction = "lean"
    else:
        direction = "balanced"
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[InventorySalesRatio] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[InventorySalesRatio] fetch error: {e}")
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


def compute_inventory_sales_ratio() -> dict | None:
    """{"latest": float, "date": str, "trend_12m": {...},
    "regime": "building"/"lean"/"balanced"} or None if the feed can't be
    fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_inventory_sales_ratio(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_inventory_sales_ratio()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
