"""U.S. Trade Balance (FRED BOPGSTB) -- goods & services net exports macro
badge.

The first trade-category macro badge shipped: every existing macro badge
covers labor, inflation, credit, output, capex, demand, or housing, but none
track the external-sector/net-exports side of GDP. A widening deficit
(more negative) signals import-heavy demand and dollar-supply pressure; a
narrowing deficit signals export strength or import contraction -- both
feed directly into GDP-growth and currency-regime read-throughs, pairing
naturally with the already-shipped Broad Dollar Index badge.

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BOPGSTB"
_CACHE_TTL_S = 3600  # BOPGSTB updates monthly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py/durable_goods_client.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    # BOPGSTB is a negative-valued deficit series: a lower (more negative)
    # reading is a WIDER deficit, not a narrower one -- z-sign is inverted
    # relative to every other _trend() in this codebase.
    if z < -0.5:
        direction = "widening"
    elif z > 0.5:
        direction = "narrowing"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[TradeBalance] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[TradeBalance] fetch error: {e}")
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


def compute_trade_balance() -> dict | None:
    """{"latest": float (millions USD, negative=deficit), "date": str,
    "change_mom": float, "trend_12m": {...}, "regime": "widening"/
    "narrowing"/"stable"} or None if the feed can't be fetched or has too
    little history."""
    series = _fetch_series()
    if not series or len(series) < 13:
        return None

    values = [v for _, v in series]
    trend_12m = _trend(values[-13:])
    if trend_12m is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_mom = latest_val - prev_val

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_mom": round(change_mom, 2),
        "trend_12m": trend_12m,
        "regime": trend_12m["direction"],
    }


def get_trade_balance(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_trade_balance()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
