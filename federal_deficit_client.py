"""Federal Surplus/Deficit (FRED MTSDS133FMS) -- fiscal-policy macro badge.

Monthly Treasury Statement basis: the U.S. federal government's monthly
cash surplus/deficit. Every existing macro badge covers monetary policy
(NFCI, M2V, ON-RRP), household finance (savings rate, disposable income,
credit card delinquency), corporate profitability, or trade -- none track
the fiscal side, i.e. how much the government itself is spending relative
to what it collects. A widening deficit trend feeds directly into Treasury
issuance pressure, pairing naturally with the already-shipped Treasury
Auction Demand badge.

Raw monthly values alternate sign heavily (tax-season inflows vs. outlay-
heavy months), so a z-score on raw months would just track the seasonal
calendar rather than the real trend -- verified live: Apr 2026 +$215bn,
May 2026 -$293bn, Jun 2026 -$120bn. Instead this uses a trailing 12-month
rolling sum (annualized deficit run-rate), which is smooth and comparable
across periods, and z-scores THAT series.

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MTSDS133FMS"
_CACHE_TTL_S = 21600  # MTSDS133FMS updates monthly; 6h refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as trade_balance_client.py's _trend() -- MTSDS133FMS's rolling
    sum is a negative-valued deficit series: a lower (more negative) reading
    is a WIDER deficit, not a narrower one, so the sign convention is
    inverted relative to most _trend() implementations in this codebase."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z < -0.5:
        direction = "widening"
    elif z > 0.5:
        direction = "narrowing"
    else:
        direction = "stable"
    return {"latest": round(latest, 1), "mean": round(mean, 1), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[FederalDeficit] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[FederalDeficit] fetch error: {e}")
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


def _rolling_12m_sums(values: list[float]) -> list[float]:
    """Trailing 12-month sum at each point (annualized deficit run-rate),
    smoothing out the monthly tax/outlay seasonality."""
    return [sum(values[i - 11:i + 1]) for i in range(11, len(values))]


def compute_federal_deficit() -> dict | None:
    """{"latest_month": float (millions USD, single month), "date": str,
    "rolling_12m_deficit": float (millions USD, trailing-annual run-rate),
    "trend_12m_rolling": {...}, "regime": "widening"/"narrowing"/"stable"}
    or None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 32:
        return None

    values = [v for _, v in series]
    rolling = _rolling_12m_sums(values)
    trend = _trend(rolling[-20:])
    if trend is None:
        return None

    latest_date, latest_month_val = series[-1]

    return {
        "latest_month": round(latest_month_val, 1),
        "date": latest_date,
        "rolling_12m_deficit": round(rolling[-1], 1),
        "trend_12m_rolling": trend,
        "regime": trend["direction"],
    }


def get_federal_deficit(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_federal_deficit()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
