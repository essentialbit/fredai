"""Nonfarm Business Sector Labor Productivity (FRED OPHNFB) -- macro badge.

OPHNFB tracks quarterly real output per hour worked. Distinct from the
already-shipped wage-cost cluster (Average Hourly Earnings, Employment Cost
Index), which measures compensation growth, not efficiency growth. The
spread between productivity growth and wage growth is a classic
unit-labor-cost inflation pressure gauge: wages outpacing productivity
signals cost-push inflation risk, productivity outpacing wages signals
margin expansion / disinflationary slack.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge -- never curl, see the documented HTTP/2 gotcha in
project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=OPHNFB"
_CACHE_TTL_S = 21600  # 6h; OPHNFB is quarterly, no need to refetch often

_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as wti_crude_oil_client.py's _trend()."""
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
            print(f"[Productivity] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[Productivity] fetch error: {e}")
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


def compute_labor_productivity() -> dict | None:
    """{"latest": float (index, 2017=100), "date": str, "yoy_change_pct": float,
    "trend_8q": {...}, "regime": "rising"/"falling"/"stable"} or None if the
    feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 9:
        return None

    values = [v for _, v in series]
    trend_8q = _trend(values[-8:])
    if trend_8q is None:
        return None

    latest_date, latest_val = series[-1]
    yoy_change_pct = None
    if len(series) >= 5:
        year_ago_val = series[-5][1]
        if year_ago_val:
            yoy_change_pct = (latest_val - year_ago_val) / year_ago_val * 100

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "yoy_change_pct": round(yoy_change_pct, 2) if yoy_change_pct is not None else None,
        "trend_8q": trend_8q,
        "regime": trend_8q["direction"],
    }


def get_labor_productivity(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_labor_productivity()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
