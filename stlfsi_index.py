"""St. Louis Fed Financial Stress Index (STLFSI4) -- weekly composite of 18
interest-rate, yield-spread, and volatility variables into one standardized
score where 0 represents historical-average financial stress. Distinct from
NFCI (broad ~105-indicator financial-conditions composite): STLFSI4 is
narrower and volatility/credit-market focused, and its bands are tuned to
its own documented stress thresholds rather than NFCI's zero-centered
tightening/loosening framing.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (jobless claims, breakeven inflation, NFCI, dollar
index) -- never curl, see the documented HTTP/2 gotcha.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=STLFSI4"
_CACHE_TTL_S = 3600 * 12  # STLFSI4 updates weekly; 12h refetch is plenty


class _Cache:
    computed_at: float = 0.0
    data: dict | None = None


_cache = _Cache()


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
            print(f"[STLFSI] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[STLFSI] fetch error: {e}")
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


def _classify(value: float) -> str:
    """Bands per the proposal spec, anchored to STLFSI4's own documented
    stress thresholds (not a relative z-score banding, same absolute-
    threshold justification as nfci_index.py/epu_index.py)."""
    if value > 1.5:
        return "high_stress"
    if value > 0.0:
        return "above_average_stress"
    if value >= -1.0:
        return "normal"
    return "low_stress"


def compute_stlfsi_index() -> dict | None:
    """{"latest": float, "date": str, "change_wow": float, "trend_20d": {...},
    "regime": "high_stress"/"above_average_stress"/"normal"/"low_stress"}
    or None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    trend_20d = _trend(values[-21:])
    if trend_20d is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_wow": round(latest_val - prev_val, 3),
        "trend_20d": trend_20d,
        "regime": _classify(latest_val),
    }


def get_stlfsi_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache.data is None or now - _cache.computed_at > _CACHE_TTL_S:
        data = compute_stlfsi_index()
        if data:
            _cache.data = data
            _cache.computed_at = now
    return _cache.data
