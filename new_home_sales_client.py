"""New Home Sales (FRED HSN1F) -- new-construction closings macro badge.

New single-family home sales complete housing-activity coverage alongside
the three already-shipped housing badges: Housing Starts/Permits track
builder intent-to-build, Existing Home Sales tracks resale transaction
volume, and Case-Shiller tracks price level -- none of them surface
new-construction closings, the builder-side demand-realization signal this
badge fills in.

Positive-valued series (seasonally adjusted annual rate of units sold) --
higher reading = more sales activity, no sign-flip needed in _trend().

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=HSN1F"
_CACHE_TTL_S = 3600  # HSN1F updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as existing_home_sales_client.py/trade_balance_client.py's _trend()."""
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
            print(f"[NewHomeSales] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[NewHomeSales] fetch error: {e}")
        return None

    out = []
    for row in rows[1:]:
        if len(row) != 2 or row[1] in ("", "."):
            continue
        try:
            out.append((row[0], float(row[1])))
        except ValueError:
            continue
    return out or None


def compute_new_home_sales() -> dict | None:
    """{"latest": float, "date": str, "trend": {...}, "regime": str} where
    regime is trend["direction"] ("rising"/"falling"/"stable"), or None if
    the series can't be fetched or has too few points."""
    series = _fetch_series()
    if not series or len(series) < 8:
        return None

    values = [v for _, v in series]
    trend = _trend(values)
    if trend is None:
        return None

    return {
        "latest": round(values[-1], 1),
        "date": series[-1][0],
        "trend": trend,
        "regime": trend["direction"],
    }


def get_new_home_sales(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_new_home_sales()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
