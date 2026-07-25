"""Initial jobless claims (ICSA) -- weekly leading labor-market indicator.

Claims turn up before broad unemployment prints and well ahead of recession
calls. Fetched directly from the St. Louis Fed's public fredgraph.csv
endpoint (no API key, no rate limiting observed) -- distinct from
nasdaq_client.py's Nasdaq Data Link wrapper, which requires a paid key for
non-preview rows on most FRED-mirrored series.

Same trend-classification shape as copper_gold_ratio.py::_trend() (rolling
z-score over a trailing window, excluding the latest point from its own
baseline), reused here for internal consistency across macro-strip badges.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=ICSA"
_CACHE_TTL_S = 86400  # daily -- ICSA only updates weekly (Thursdays)
_ELEVATED_LEVEL = 300_000  # historical rough threshold for labor-market stress
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential)."""
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
    return {"latest": round(latest, 1), "mean": round(mean, 1), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[JoblessClaims] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[JoblessClaims] fetch error: {e}")
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


def compute_jobless_claims() -> dict | None:
    """{"latest": float, "date": str, "change_wow": float, "trend_8w": {...},
    "level_flag": "elevated"/"normal", "series_8w": [{"date","value"}, ...]}
    or None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 9:
        return None

    values = [v for _, v in series]
    trend_8w = _trend(values[-9:])
    if trend_8w is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    return {
        "latest": latest_val,
        "date": latest_date,
        "change_wow": round(latest_val - prev_val, 1),
        "trend_8w": trend_8w,
        "level_flag": "elevated" if latest_val >= _ELEVATED_LEVEL else "normal",
        "series_8w": [{"date": d, "value": v} for d, v in series[-8:]],
    }


def get_jobless_claims(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_jobless_claims()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
