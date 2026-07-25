"""Commercial & Industrial Loan Volume (FRED BUSLOANS) -- realized bank
credit-creation macro badge.

Distinct from the already-shipped lending-standards diffusion indices
(DRTSCILM/DRTSCLCC, survey-based bank willingness-to-lend), this tracks
actual loan volume: year-over-year growth in C&I loans outstanding at all
commercial banks. Loan growth typically peaks late-cycle and contracts
sharply heading into recessions, making it a classic credit-cycle
leading/coincident indicator that pairs with the lending-standards badges
without duplicating them.

Same free, keyless fredgraph.csv fetch pattern proven for every other
FRED-sourced badge -- never curl, see the documented HTTP/2 stream-reset
gotcha in project memory; plain requests.get matches every shipped FRED
client's real code path.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BUSLOANS"
_CACHE_TTL_S = 3600  # BUSLOANS updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as trade_balance_client.py/copper_gold_ratio.py's _trend()."""
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
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[BusinessLoans] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[BusinessLoans] fetch error: {e}")
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


def compute_business_loan_growth() -> dict | None:
    """{"latest_level": float ($bn, SA), "date": str, "yoy_growth_pct": float,
    "trend_24m": {...} (z-scored against trailing 24 months of YoY growth),
    "regime": "expanding"/"contracting"/"stable"} or None if the feed can't
    be fetched or has too little history for a 12-month-lookback YoY series."""
    series = _fetch_series()
    if not series or len(series) < 37:  # 24mo trend window + 12mo YoY lookback + 1
        return None

    dates = [d for d, _ in series]
    values = [v for _, v in series]

    yoy_growth = []
    for i in range(12, len(values)):
        prior = values[i - 12]
        if prior:
            yoy_growth.append((values[i] - prior) / prior * 100)

    if len(yoy_growth) < 25:
        return None

    trend_24m = _trend(yoy_growth[-25:])
    if trend_24m is None:
        return None

    return {
        "latest_level": round(values[-1], 3),
        "date": dates[-1],
        "yoy_growth_pct": round(yoy_growth[-1], 2),
        "trend_24m": trend_24m,
        "regime": trend_24m["direction"],
    }


def get_business_loan_growth(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_business_loan_growth()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
