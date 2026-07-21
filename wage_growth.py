"""Average Hourly Earnings (FRED CES0500000003) -- labor-cost inflation
macro-strip badge.

Tracks month-over-month growth in average hourly earnings for all
private-sector employees. Distinct from every other shipped labor-market
badge: JOLTS (job openings) and Continuing/Initial Jobless Claims track
labor *quantity* (demand/slack), while this tracks labor *cost* -- a
direct leading input to wage-driven inflation pressure and consumer
purchasing power that nothing shipped so far covers.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (jobless claims, Core PCE, PPI, retail sales, NFCI)
-- never curl, see the documented HTTP/2 gotcha.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CES0500000003"
_CACHE_TTL_S = 3600  # monthly series; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as nfci_index.py's/copper_gold_ratio.py's _trend()."""
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
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[WageGrowth] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[WageGrowth] fetch error: {e}")
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


def compute_wage_growth() -> dict | None:
    """{"latest": float, "date": str, "mom_pct": float, "yoy_pct": float,
    "trend_12m": {...}, "regime": "hot"/"moderate"/"cool"} or None if the
    feed can't be fetched or has too little history.

    Regime bands are relative to the trailing 12-month MoM% z-score
    (trend_12m), not an absolute anchor -- unlike NFCI, wage growth has no
    natural zero-centered baseline, so a rolling z-score is the right
    comparison (same relative-only approach as sector_rotation.py)."""
    series = _fetch_series()
    if not series or len(series) < 14:
        return None

    dates = [d for d, _ in series]
    values = [v for _, v in series]

    mom_series = [
        (values[i] - values[i - 1]) / values[i - 1] * 100
        for i in range(1, len(values))
        if values[i - 1]
    ]
    if len(mom_series) < 13:
        return None

    trend_12m = _trend(mom_series[-13:])
    if trend_12m is None:
        return None

    latest_val = values[-1]
    yoy_pct = None
    if len(values) >= 13 and values[-13]:
        yoy_pct = (latest_val - values[-13]) / values[-13] * 100

    if trend_12m["direction"] == "accelerating":
        regime = "hot"
    elif trend_12m["direction"] == "decelerating":
        regime = "cool"
    else:
        regime = "moderate"

    return {
        "latest": round(latest_val, 2),
        "date": dates[-1],
        "mom_pct": round(mom_series[-1], 3),
        "yoy_pct": round(yoy_pct, 2) if yoy_pct is not None else None,
        "trend_12m": trend_12m,
        "regime": regime,
    }


def get_wage_growth(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_wage_growth()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
