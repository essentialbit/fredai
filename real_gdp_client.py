"""Real GDP growth (FRED GDPC1) -- headline economic-output macro badge.

Every FSI L2 macro badge shipped so far tracks a monthly or weekly series
(labor market, housing, inflation, credit). None track GDP itself -- the
single most-cited quarterly growth number and the series most macro-regime
frameworks (including issue #103's design) anchor on. GDPC1 is real GDP,
chained 2017 dollars, seasonally adjusted annual rate, released quarterly.

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.

GDPC1 is a price *level* (billions of chained dollars), not a growth rate,
and levels trend monotonically upward over any long window -- a z-score on
the raw level would always read "rising" and say nothing useful. Convert to
quarter-over-quarter annualized growth rate first, then trend that.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPC1"
_CACHE_TTL_S = 21600  # GDPC1 updates quarterly; 6h refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as unemployment_rate_client.py's _trend(), applied to the
    QoQ annualized growth-rate series rather than a raw level -- so
    "rising"/"falling" would be misleading (growth itself, not the economy's
    size, is what's moving); direction is named accelerating/decelerating
    instead."""
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


def _qoq_annualized_growth(levels: list[float]) -> list[float]:
    """QoQ annualized growth rate: ((level[i]/level[i-1])**4 - 1) * 100."""
    growth = []
    for prev, cur in zip(levels, levels[1:]):
        if prev <= 0:
            continue
        growth.append(((cur / prev) ** 4 - 1) * 100)
    return growth


def compute_real_gdp() -> dict | None:
    """{"latest_growth_pct": float, "prior_growth_pct": float,
    "trend_8q": {...}, "regime"} (regime is "contracting" whenever the
    latest quarter's annualized growth is negative -- outright contraction
    is always surfaced regardless of the z-score, since GDP crossing zero
    is meaningful on its own -- otherwise "accelerating"/"decelerating"/
    "stable" from the trailing-8-quarter z-score), or None if the FRED
    fetch fails or there isn't enough history yet."""
    try:
        levels = _fetch_series()
    except (requests.RequestException, ValueError):
        return None
    if len(levels) < 10:
        return None

    growth = _qoq_annualized_growth(levels)
    if len(growth) < 9:
        return None

    window = growth[-9:]
    trend_8q = _trend(window)
    if trend_8q is None:
        return None

    latest_growth_pct = round(growth[-1], 2)
    regime = "contracting" if latest_growth_pct < 0 else trend_8q["direction"]

    return {
        "latest_growth_pct": latest_growth_pct,
        "prior_growth_pct": round(growth[-2], 2),
        "trend_8q": trend_8q,
        "regime": regime,
    }


def get_real_gdp(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_real_gdp()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
