"""Moody's Aaa-Baa corporate bond quality spread -- within-credit-quality
flight-to-quality signal (FSI L2).

Distinct from the already-shipped Baa-to-10-Year-Treasury spread badge,
which measures corporate risk premium over the risk-free rate. This spread
(BAA yield - AAA yield) instead measures dispersion within the corporate
bond market itself: it widens as investors flee lower-rated corporate debt
for higher-rated corporate debt, independent of any treasury-relative move,
and is a classic credit-analyst leading signal ahead of recessions.

FRED series, fetched via plain requests.get (never curl, which false-
positives an HTTP/2 stream reset on this endpoint -- see project memory).
"""
import statistics
import time

import requests

_CACHE_TTL_S = 3600  # monthly-cadence series, 1h TTL matches other FRED badges
_cache: dict = {"computed_at": 0.0, "data": None}

_AAA_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA"
_BAA_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA"


def _fetch_series(url: str) -> list[float] | None:
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return None
    lines = resp.text.strip().splitlines()[1:]  # skip header row
    values = []
    for line in lines:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        try:
            values.append(float(parts[1]))
        except ValueError:
            continue  # FRED uses "." for missing observations
    return values or None


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
        direction = "widening"
    elif z < -0.5:
        direction = "narrowing"
    else:
        direction = "stable"
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def compute_moody_credit_quality_spread() -> dict | None:
    """{"spread": float, "trend": {...}, "regime"} or None if either series
    can't be fetched. regime is "flight_to_quality"/"risk_on"/"stable",
    derived from the trailing-window z-score direction of the spread
    (BAA - AAA, always positive: wider = more within-credit dispersion)."""
    aaa = _fetch_series(_AAA_URL)
    baa = _fetch_series(_BAA_URL)
    if not aaa or not baa:
        return None

    n = min(len(aaa), len(baa))
    spread_series = [b - a for a, b in zip(aaa[-n:], baa[-n:])]
    if len(spread_series) < 8:
        return None

    trend = _trend(spread_series)
    if trend is None:
        return None

    if trend["direction"] == "widening":
        regime = "flight_to_quality"
    elif trend["direction"] == "narrowing":
        regime = "risk_on"
    else:
        regime = "stable"

    return {
        "spread": round(spread_series[-1], 2),
        "trend": trend,
        "regime": regime,
    }


def get_moody_credit_quality_spread(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_moody_credit_quality_spread()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
