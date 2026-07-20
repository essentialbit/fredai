"""University of Michigan Consumer Sentiment Index (UMCSENT) -- monthly
household-survey-based macro-strip badge.

Distinct from every other shipped macro badge: NFCI/credit-spread/
yield-curve/VIX/dollar-index are all market-price-derived, and EPU is a
news-text-mining measure, while UMCSENT is the only survey-based
consumer-psychology gauge -- a well-established leading indicator for
consumer spending and retail-sector demand.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (jobless claims, breakeven inflation, NFCI) -- never
curl, see the documented HTTP/2 gotcha. UMCSENT is monthly (not weekly/
daily like every currently-shipped badge), so the trend window is sized
to 13 monthly points instead of 20-21 daily/weekly ones, and the cache
TTL is a full day instead of the 15min/1h TTLs used by faster-moving
badges.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT"
_CACHE_TTL_S = 86400  # UMCSENT updates monthly; daily refetch is plenty
_LONG_RUN_AVG = 87.0  # UMCSENT's own long-run historical average
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/nfci_index.py's _trend(), sized to
    12 trailing monthly points instead of 20-21 daily/weekly ones."""
    if len(series) < 6:
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
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[UMCSENT] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[UMCSENT] fetch error: {e}")
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


def compute_consumer_sentiment() -> dict | None:
    """{"latest": float, "date": str, "change_mom": float, "trend_13m": {...},
    "regime": "weak"/"soft"/"healthy"} or None if the feed can't be fetched
    or has too little history.

    Bands are anchored to UMCSENT's own long-run historical average (~87)
    since, unlike NFCI, it is not naturally zero-centered by construction --
    same absolute-banding approach as epu_index.py."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_13m = _trend(values[-13:])
    if trend_13m is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]

    if latest_val < _LONG_RUN_AVG - 20:
        regime = "weak"
    elif latest_val < _LONG_RUN_AVG - 5:
        regime = "soft"
    else:
        regime = "healthy"

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_mom": round(latest_val - prev_val, 3),
        "trend_13m": trend_13m,
        "regime": regime,
    }


def get_consumer_sentiment(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_consumer_sentiment()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
