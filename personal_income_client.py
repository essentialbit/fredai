"""Real Disposable Personal Income (FRED DSPIC96) -- household income-level
macro badge.

Household balance-sheet badges shipped so far cover the debt side (Consumer
Credit) and the surplus side (Savings Rate), but not the income level both
are measured against. DSPIC96 (monthly, billions of chained 2017 dollars)
closes that gap -- the third leg of the household-finance triangle
(earn / spend-save / borrow).

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DSPIC96"
_CACHE_TTL_S = 3600  # DSPIC96 updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py/trade_balance_client.py's _trend()."""
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
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[PersonalIncome] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[PersonalIncome] fetch error: {e}")
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


def compute_personal_income() -> dict | None:
    """{"latest": float (billions, chained 2017 dollars), "date": str,
    "change_mom_pct": float, "trend_12m": {...}, "regime": "rising"/"falling"/
    "stable"} or None if the feed can't be fetched or has too little
    history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_mom_pct = ((latest_val - prev_val) / prev_val * 100) if prev_val else 0.0

    return {
        "latest": round(latest_val, 1),
        "date": latest_date,
        "change_mom_pct": round(change_mom_pct, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_personal_income(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_personal_income()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
