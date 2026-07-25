"""ICE BofA Option-Adjusted Spread (OAS) credit-stress macro-strip badge.

Tracks the actual spread level in basis points that credit markets and
recession-risk models watch -- distinct from the already-shipped HYG-vs-LQD
relative-strength badge (credit_spread.py), which tracks price momentum
between two ETFs, not the underlying spread level itself. Fills MISSION.md's
L4 "Credit default swap spread monitoring" line with real spread-level data.

Two series: BAMLH0A0HYM2 (high-yield OAS) drives the regime classification
(absolute banding anchored to well-known historical stress thresholds, same
justification pattern as epu_index.py/nfci_index.py); BAMLC0A0CM
(investment-grade OAS) is carried alongside for context. Same free
fredgraph.csv fetch pattern already used by every other FRED-sourced badge
-- never curl, see the documented HTTP/2 gotcha.
"""
import csv
import io
import statistics
import time

import requests

_HY_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"
_IG_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC0A0CM"
_CACHE_TTL_S = 3600  # daily series; hourly refetch is plenty
_CRISIS_BPS = 8.0
_TIGHT_BPS = 3.5
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/nfci_index.py's _trend()."""
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
        direction = "tightening"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series(url: str, label: str) -> list[tuple[str, float]] | None:
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"[CreditOAS] {label} HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[CreditOAS] {label} fetch error: {e}")
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


def _band(latest_hy: float) -> str:
    if latest_hy >= _CRISIS_BPS:
        return "crisis"
    if latest_hy <= _TIGHT_BPS:
        return "complacent_tight"
    return "normal"


def compute_credit_oas_spread() -> dict | None:
    """{"hy_oas": float, "ig_oas": float, "date": str, "trend_20d": {...},
    "regime": "crisis"/"normal"/"complacent_tight"} or None if either feed
    can't be fetched or has too little history."""
    hy_series = _fetch_series(_HY_URL, "HY")
    ig_series = _fetch_series(_IG_URL, "IG")
    if not hy_series or not ig_series or len(hy_series) < 21:
        return None

    hy_values = [v for _, v in hy_series]
    trend_20d = _trend(hy_values[-21:])
    if trend_20d is None:
        return None

    latest_date, latest_hy = hy_series[-1]
    latest_ig = ig_series[-1][1]
    return {
        "hy_oas": latest_hy,
        "ig_oas": latest_ig,
        "date": latest_date,
        "trend_20d": trend_20d,
        "regime": _band(latest_hy),
    }


def get_credit_oas_spread(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_credit_oas_spread()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
