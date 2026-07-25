"""Household Net Worth (FRED TNWBSHNO) -- quarterly household-wealth
macro badge.

Federal Reserve Z.1 Financial Accounts measure of aggregate US household and
nonprofit-organization net worth (assets minus liabilities). Existing
household-finance badges cover income (Real Disposable Personal Income),
debt (Consumer Credit Outstanding), and savings flow (Personal Savings
Rate) -- all flow measures. None track the wealth stock itself: the actual
balance-sheet bottom line the Fed watches for wealth-effect-driven
consumption shifts. Distinct stock-vs-flow measure, not a duplicate of that
already-closed household-balance-sheet triangle.

TNWBSHNO is a nominal dollar level (millions) that trends monotonically
upward over time like every other level series -- convert to year-over-year
percent change first, then trend that, same pattern as
corporate_profits_client.py/real_gdp_client.py use for their own
level-to-growth conversions.

Same free, keyless fredgraph.csv fetch pattern already proven for every
other FRED-sourced badge -- never curl, see the documented HTTP/2
stream-reset gotcha in project memory; plain requests.get matches every
shipped FRED client's real code path.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TNWBSHNO"
_CACHE_TTL_S = 21600  # TNWBSHNO updates quarterly; 6h refetch is plenty

_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as corporate_profits_client.py's/real_gdp_client.py's
    _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "expanding"
    elif z < -0.5:
        direction = "contracting"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[HouseholdNetWorth] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[HouseholdNetWorth] fetch error: {e}")
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


def _yoy_growth(levels: list[float]) -> list[float]:
    """Year-over-year percent change, quarterly series so 4 periods back."""
    growth = []
    for i in range(4, len(levels)):
        prev = levels[i - 4]
        if prev <= 0:
            continue
        growth.append((levels[i] / prev - 1) * 100)
    return growth


def compute_household_net_worth() -> dict | None:
    """{"latest_yoy_pct": float, "date": str, "trend_8q": {...},
    "regime": "expanding"/"contracting"/"stable"} or None if the feed
    can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    dates = [d for d, _ in series]
    levels = [v for _, v in series]
    growth = _yoy_growth(levels)
    if len(growth) < 9:
        return None

    window = growth[-9:]
    trend_8q = _trend(window)
    if trend_8q is None:
        return None

    return {
        "latest_yoy_pct": round(growth[-1], 2),
        "date": dates[-1],
        "trend_8q": trend_8q,
        "regime": trend_8q["direction"],
    }


def get_household_net_worth(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_household_net_worth()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
