"""Continuing Jobless Claims (FRED CCSA) -- unemployment-duration stock
signal macro badge.

Distinct from Initial Claims (already shipped, jobless_claims_client.py):
Initial Claims is the weekly flow of new layoffs; Continuing Claims is the
stock of people still claiming benefits week over week. A rising
Continuing Claims print alongside flat Initial Claims signals workers are
struggling to find new jobs even without a fresh layoff wave -- labor-
market slack building rather than a fresh shock -- a distinct regime read
the Fed and BLS both watch alongside the weekly initial-claims print.

Same free, keyless fredgraph.csv fetch pattern already proven for every
other FRED-sourced badge -- never curl, see the documented HTTP/2 stream-
reset gotcha in project memory; plain requests.get matches every shipped
FRED client's real code path.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CCSA"
_CACHE_TTL_S = 3600  # CCSA updates weekly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as jolts_openings_client.py/durable_goods_client.py's _trend()."""
    if len(series) < 13:
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
            print(f"[ContinuingClaims] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[ContinuingClaims] fetch error: {e}")
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


def compute_continuing_claims() -> dict | None:
    """{"latest": float, "date": str, "change_wow_pct": float,
    "trend_13w": {...}, "regime": "rising"/"falling"/"stable"} or
    None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 14:
        return None

    values = [v for _, v in series]
    trend_13w = _trend(values[-14:])
    if trend_13w is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_wow_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None
    if change_wow_pct is None:
        return None

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_wow_pct": round(change_wow_pct, 2),
        "trend_13w": trend_13w,
        "regime": trend_13w["direction"],
    }


def get_continuing_claims(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_continuing_claims()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
