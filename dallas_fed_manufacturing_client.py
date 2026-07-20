"""Dallas Fed Texas Manufacturing Outlook Survey -- General Business Activity
Index (FRED BACTSAMFRBDAL) regional manufacturing sentiment macro-strip badge.

Third regional Fed manufacturing survey badge alongside Empire State
(empire_state_manufacturing_client.py, NY district) and Philly Fed
(philly_fed_client.py, Philadelphia district). Distinct district (Dallas),
distinct panel of respondents (Texas Manufacturing Outlook Survey), not a
duplicate of either already-shipped series.

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.

Like Empire State and Philly Fed, this is already a mean-reverting
diffusion index centered near zero, so it's trended directly -- no
YoY/growth-rate conversion needed. Regime bands use the survey's own
convention (>0 expansion, <0 contraction) combined with the z-score
direction for rate-of-change.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BACTSAMFRBDAL"
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
        direction = "improving"
    elif z < -0.5:
        direction = "deteriorating"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[DallasFedManufacturing] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[DallasFedManufacturing] fetch error: {e}")
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


def compute_dallas_fed_manufacturing() -> dict | None:
    """{"latest": float, "date": str, "trend_12m": {...}, "expansion": bool,
    "regime": "improving"/"deteriorating"/"stable"} or None if the feed
    can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]

    return {
        "latest": round(latest_val, 2),
        "date": latest_date,
        "trend_12m": trend_12m,
        "expansion": latest_val > 0,
        "regime": trend_12m["direction"],
    }


def get_dallas_fed_manufacturing(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_dallas_fed_manufacturing()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
