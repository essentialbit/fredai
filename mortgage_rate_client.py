"""30-Year Fixed Mortgage Rate (FRED MORTGAGE30US) -- financing-cost macro badge.

Freddie Mac's weekly Primary Mortgage Market Survey average. This is the
specific borrowing-cost signal households face on a new home loan -- distinct
from the broad Treasury-yield/2s10s badges already shipped, which capture
rate levels but not consumer mortgage pricing. Pairs with the housing-
activity cluster (Starts/Permits, Existing/New Home Sales, Case-Shiller) as
the financing-cost leg that drives affordability and transaction volume.

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.

MORTGAGE30US is a positive-valued rate -- standard sign convention applies:
a higher reading means tighter financing conditions (rates rising), not the
inverted deficit-style convention some other badges (e.g. trade balance)
need.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"
_CACHE_TTL_S = 3600  # weekly series; 1h refetch is plenty
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
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[float]:
    r = requests.get(_CSV_URL, timeout=15)
    r.raise_for_status()
    reader = csv.reader(io.StringIO(r.text))
    next(reader, None)  # header row
    values = []
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            values.append(float(row[1]))
        except ValueError:
            continue
    return values


def compute_mortgage_rate() -> dict | None:
    """{"latest_rate": float, "prior_rate": float, "trend_26w": {...},
    "regime"} (regime is "tightening"/"easing"/"stable" from the trailing
    26-week z-score direction, renamed for financing-conditions framing),
    or None if the FRED fetch fails or there isn't enough history yet."""
    try:
        values = _fetch_series()
    except (requests.RequestException, ValueError):
        return None
    if len(values) < 9:
        return None

    window = values[-27:] if len(values) >= 27 else values
    trend_26w = _trend(window)
    if trend_26w is None:
        return None

    direction_to_regime = {"rising": "tightening", "falling": "easing", "stable": "stable"}

    return {
        "latest_rate": round(values[-1], 2),
        "prior_rate": round(values[-2], 2),
        "trend_26w": trend_26w,
        "regime": direction_to_regime[trend_26w["direction"]],
    }


def get_mortgage_rate(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_mortgage_rate()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
