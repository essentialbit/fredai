"""Commercial paper outstanding -- short-term corporate funding market
stress signal (FRED series COMPOUT).

Commercial paper is unsecured short-term corporate debt used to fund
working capital and payroll. A sharp contraction in total outstanding
volume is a classic early warning of short-term funding market stress
(issuers unable to roll maturing paper, forced to draw down bank credit
lines instead -- seen ahead of both 2008 and 2020). This is a volume
signal, distinct from every already-shipped rate-based funding metric
(SOFR-EFFR repo spread, ICE BofA OAS, Moody's Baa/10Y spread).

Public, keyless FRED CSV endpoint -- plain requests.get, matching the
project's proven direct-endpoint pattern (curl+HTTP/2 has been flaky
against fred.stlouisfed.org before, requests.get is not).
"""
import statistics
import time

import requests

_SERIES_ID = "COMPOUT"
_CACHE_TTL_S = 3600  # 1h -- weekly-cadence series, matching nasdaq_client.py macro TTL
_cache: dict = {"computed_at": 0.0, "data": None}


def _fetch_series() -> list[float]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={_SERIES_ID}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    values = []
    for line in r.text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 2 or not parts[1]:
            continue
        try:
            values.append(float(parts[1]))
        except ValueError:
            continue
    return values


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point). Same shape as copper_gold_ratio.py's
    _trend() helper."""
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


def _period_change_pct(series: list[float], weeks: int) -> float | None:
    if len(series) < weeks + 1:
        return None
    start, end = series[-(weeks + 1)], series[-1]
    if not start:
        return None
    return (end - start) / start * 100


def compute_commercial_paper() -> dict | None:
    """{"outstanding_billions": float, "change_4w_pct": float,
    "trend_13w": {...}, "regime"} (regime is "stress"/"neutral"/"healthy",
    derived from the 13-week rolling z-score direction), or None if the
    series can't be fetched."""
    try:
        series = _fetch_series()
    except Exception:
        return None
    if len(series) < 14:
        return None

    trend_13w = _trend(series[-13:])
    change_4w_pct = _period_change_pct(series, 4)
    if trend_13w is None or change_4w_pct is None:
        return None

    if trend_13w["direction"] == "contracting":
        regime = "stress"
    elif trend_13w["direction"] == "expanding":
        regime = "healthy"
    else:
        regime = "neutral"

    return {
        "outstanding_billions": round(series[-1], 2),
        "change_4w_pct": round(change_4w_pct, 2),
        "trend_13w": trend_13w,
        "regime": regime,
    }


def get_commercial_paper(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_commercial_paper()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
