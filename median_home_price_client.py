"""Median Sales Price of Houses Sold in the US (FRED MSPUS) -- housing-price
macro badge.

Every existing housing badge tracks either construction activity (starts,
permits, existing/new home sales volume) or a repeat-sales appreciation
index (Case-Shiller). None track the absolute median transaction price
level -- the number most consumers and media coverage actually cite.
MSPUS is Census/HUD-sourced via FRED, released quarterly.

Same free, keyless fredgraph.csv fetch pattern already proven for every
other FRED-sourced badge -- never curl, see the documented HTTP/2
stream-reset gotcha in project memory; plain requests.get matches every
shipped FRED client's real code path.

MSPUS is a price *level* in dollars, not a growth rate. Unlike GDPC1
(where the level always trends upward and only the growth-rate derivative
is informative), the level itself is the number people care about here --
same shape as case_shiller_client.py's "appreciating"/"depreciating"/
"stable" regime read off the raw level's z-score, adapted to MSPUS's
quarterly (not monthly) update cadence.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MSPUS"
_CACHE_TTL_S = 21600  # MSPUS updates quarterly; 6h refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as case_shiller_client.py's _trend(), over a trailing
    8-quarter window (mirrors real_gdp_client.py's quarterly-cadence
    trend_8q pattern) instead of 12 months."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "appreciating"
    elif z < -0.5:
        direction = "depreciating"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[MedianHomePrice] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[MedianHomePrice] fetch error: {e}")
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


def compute_median_home_price() -> dict | None:
    """{"latest": float, "date": str, "change_yoy_pct": float,
    "trend_8q": {...}, "regime": "appreciating"/"depreciating"/"stable"} or
    None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 9:
        return None

    values = [v for _, v in series]
    trend_8q = _trend(values[-9:])
    if trend_8q is None:
        return None

    latest_date, latest_val = series[-1]
    prev_year_val = series[-5][1]  # 4 quarters back = 1 year, quarterly cadence
    change_yoy_pct = (latest_val - prev_year_val) / prev_year_val * 100 if prev_year_val else None
    if change_yoy_pct is None:
        return None

    return {
        "latest": round(latest_val, 2),
        "date": latest_date,
        "change_yoy_pct": round(change_yoy_pct, 2),
        "trend_8q": trend_8q,
        "regime": trend_8q["direction"],
    }


def get_median_home_price(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_median_home_price()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
