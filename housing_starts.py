"""Housing starts & building permits (FRED HOUST/PERMIT) -- real-economy
leading-indicator macro badge.

Housing is one of the most cyclical, rate-sensitive sectors of the economy:
starts/permits turn down well before broader GDP or labor-market weakness
shows up, and permits (issued before construction begins) lead starts by
roughly 1-2 months. Distinct from every shipped/queued macro-strip signal --
jobless claims track labor-market layoffs, NFCI/STLFSI4 are broad financial-
conditions composites, yield curve/credit spreads track rate/credit markets.
None of them isolate real-economy construction activity, the transmission
channel Fed rate moves hit first and hardest.

Same free fredgraph.csv fetch already used for the dollar index / breakeven
inflation badges (no API key, no signup), same z-score-lite _trend() shape
reused across every macro-strip badge for consistency.
"""
import csv
import io
import statistics
import time

import requests

_HOUST_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=HOUST"
_PERMIT_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PERMIT"
_CACHE_TTL_S = 21600  # 6h -- HOUST/PERMIT update once a month, hourly refetch adds no signal
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
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": round(latest, 1), "mean": round(mean, 1), "z_score": round(z, 2), "direction": direction}


def _fetch_series(url: str) -> list[tuple[str, float]] | None:
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"[HousingStarts] HTTP {r.status_code} for {url}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[HousingStarts] fetch error: {e}")
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


def compute_housing_starts() -> dict | None:
    """{"starts": {"latest", "date", "change_mom_pct", "trend_12m": {...}},
    "permits": {same shape}, "regime": "expanding"/"contracting"/"diverging"/
    "stable"} or None if either feed can't be fetched or has too little
    history. "diverging" flags the classic pre-turn signal where permits
    (leading) and starts (lagging) point opposite directions."""
    houst = _fetch_series(_HOUST_URL)
    permit = _fetch_series(_PERMIT_URL)
    if not houst or len(houst) < 13 or not permit or len(permit) < 13:
        return None

    def _leg(series: list[tuple[str, float]]) -> dict | None:
        values = [v for _, v in series]
        trend_12m = _trend(values[-13:])
        if trend_12m is None:
            return None
        latest_date, latest_val = series[-1]
        prev_val = series[-2][1]
        change_mom_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None
        return {
            "latest": latest_val,
            "date": latest_date,
            "change_mom_pct": round(change_mom_pct, 2) if change_mom_pct is not None else None,
            "trend_12m": trend_12m,
        }

    starts = _leg(houst)
    permits = _leg(permit)
    if starts is None or permits is None:
        return None

    starts_dir = starts["trend_12m"]["direction"]
    permits_dir = permits["trend_12m"]["direction"]
    if starts_dir == "rising" and permits_dir == "rising":
        regime = "expanding"
    elif starts_dir == "falling" and permits_dir == "falling":
        regime = "contracting"
    elif {starts_dir, permits_dir} == {"rising", "falling"}:
        regime = "diverging"
    else:
        regime = "stable"

    return {"starts": starts, "permits": permits, "regime": regime}


def get_housing_starts(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_housing_starts()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
