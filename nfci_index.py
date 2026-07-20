"""Chicago Fed National Financial Conditions Index (NFCI) -- broad
market-wide liquidity/leverage/risk macro-strip badge.

NFCI is a weekly composite of ~105 indicators across money markets,
debt/equity markets, and the shadow banking system, standardized so zero
represents historical-average financial conditions, positive values
represent tighter-than-average conditions, and negative values represent
looser-than-average conditions. Distinct from every other shipped macro
badge: it does not track a single asset class (unlike credit spread
HYG/LQD, yield curve 2s10s, VIX term structure, or the dollar index) but
aggregates broad conditions into one already-computed number.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (jobless claims, breakeven inflation, Fed balance
sheet/M2, dollar index) -- never curl, see the documented HTTP/2 gotcha.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NFCI"
_CACHE_TTL_S = 3600  # NFCI updates weekly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/dollar_index_client.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "tightening"
    elif z < -0.5:
        direction = "loosening"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[NFCI] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[NFCI] fetch error: {e}")
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


def compute_nfci_index() -> dict | None:
    """{"latest": float, "date": str, "change_wow": float, "trend_20d": {...},
    "regime": "calm"/"normal"/"tight"} or None if the feed can't be fetched
    or has too little history.

    Bands are anchored to NFCI's own zero-centered baseline (same absolute-
    banding approach as epu_index.py, justified here since NFCI is
    explicitly standardized around zero by construction, not a relative-
    only series)."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    trend_20d = _trend(values[-21:])
    if trend_20d is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]

    if latest_val < -0.5:
        regime = "calm"
    elif latest_val < 0.5:
        regime = "normal"
    else:
        regime = "tight"

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_wow": round(latest_val - prev_val, 3),
        "trend_20d": trend_20d,
        "regime": regime,
    }


def get_nfci_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_nfci_index()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
