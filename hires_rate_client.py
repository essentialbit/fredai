"""JOLTS Hires Rate (FRED JTSHIR) -- employer-side hiring-flow labor-market
macro badge.

The BLS Job Openings and Labor Turnover Survey hires rate (new hires as a %
of total employment) is the employer-side hiring-flow leg, distinct from
every other JOLTS-family/labor signal already shipped: JOLTS_QUITS tracks
voluntary worker-side separations (a confidence read), Job Openings (once
merged) tracks unfilled vacancies (a stock, not a flow), and this hires rate
tracks how fast employers are actually converting openings into filled jobs
-- it can diverge sharply from openings when firms post vacancies but keep
hiring frozen, a pattern that has preceded past labor-market slowdowns.

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=JTSHIR"
_CACHE_TTL_S = 3600  # JTSHIR updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as jolts_quits_client.py/durable_goods_client.py's _trend()."""
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
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[HiresRate] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[HiresRate] fetch error: {e}")
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


def compute_hires_rate() -> dict | None:
    """{"latest": float, "date": str, "change_mom_pct": float,
    "trend_12m": {...}, "regime": "accelerating"/"decelerating"/"stable"} or
    None if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_mom_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None
    if change_mom_pct is None:
        return None

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_mom_pct": round(change_mom_pct, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_hires_rate(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_hires_rate()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
