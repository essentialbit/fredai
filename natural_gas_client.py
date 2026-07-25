"""Henry Hub Natural Gas Spot Price (FRED DHHNGSP) -- energy-sector macro
badge, second leg alongside the WTI crude oil spot price badge.

Natural gas and crude oil track different demand drivers (utility/heating
and industrial gas-fired generation vs. transportation fuel and global
supply-shock exposure), so DHHNGSP is a distinct industrial/utility
input-cost signal, not a duplicate of the oil badge.

Positive-valued series, no sign-inversion needed (see trade_balance_client.py
for the negative-valued case). Fetched via plain requests.get against FRED's
CSV endpoint -- never curl, which false-positives on an HTTP/2 stream reset
against this endpoint; confirmed live this cycle with a direct probe.
"""
import statistics
import time

import requests

_CACHE_TTL_S = 3600  # daily-updated series, matching other FRED-CSV badges
_cache: dict = {"computed_at": 0.0, "data": None}

_FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_SERIES_ID = "DHHNGSP"


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing
    window (excluding the latest point), per macro_badge_template.md."""
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
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[float]:
    r = requests.get(_FRED_URL, params={"id": _SERIES_ID}, timeout=15)
    r.raise_for_status()
    values = []
    for line in r.text.strip().splitlines()[1:]:
        _, _, raw = line.partition(",")
        try:
            values.append(float(raw))
        except ValueError:
            continue  # FRED uses "." for missing observations
    return values


def compute_natural_gas() -> dict | None:
    """{"latest": float, "trend_20d": {...}, "regime"} or None on fetch
    failure. regime is "rising"/"falling"/"stable", mirrored from the
    trend direction (higher spot price = more input-cost pressure)."""
    try:
        series = _fetch_series()
    except (requests.RequestException, ValueError):
        return None
    if len(series) < 21:
        return None

    trend_20d = _trend(series[-21:])
    if trend_20d is None:
        return None

    return {
        "latest": trend_20d["latest"],
        "trend_20d": trend_20d,
        "regime": trend_20d["direction"],
    }


def get_natural_gas(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_natural_gas()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
