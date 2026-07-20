"""US Regular All Formulations Retail Gasoline Price (FRED GASREGW) --
weekly consumer energy-cost pass-through macro badge.

Existing energy-sector badges cover wholesale/futures pricing -- WTI crude
spot (DCOILWTICO) and Henry Hub natural gas spot (DHHNGSP) -- both
industrial/utility input costs. GASREGW is the retail pump price consumers
actually pay: a distinct signal that feeds directly into the energy
component of headline CPI and discretionary consumer spending capacity,
and can diverge from wholesale crude (refining margins, seasonal blend
changes, regional supply disruptions) rather than just lagging it.

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GASREGW"
_CACHE_TTL_S = 21600  # GASREGW updates weekly; 6h refetch is plenty


_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Higher pump prices are already plain-language "worse" for consumers, so
    no sign inversion is needed -- unlike a negative-valued deficit series."""
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
            print(f"[GasolinePrice] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[GasolinePrice] fetch error: {e}")
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


def compute_gasoline_price() -> dict | None:
    """{"latest": float (USD/gallon), "date": str, "change_4w_pct": float,
    "trend_20w": {...}, "regime": "rising"/"falling"/"stable"} or None if the
    feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    trend_20w = _trend(values[-20:])
    if trend_20w is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-5][1] if len(series) >= 5 else None
    change_4w_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_4w_pct": round(change_4w_pct, 2) if change_4w_pct is not None else None,
        "trend_20w": trend_20w,
        "regime": trend_20w["direction"],
    }


def get_gasoline_price(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_gasoline_price()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
