"""Federal Debt as Percent of GDP (FRED GFDEGDQ188S) -- fiscal-policy debt
burden macro badge.

Second fiscal-policy signal, genuinely distinct from the already-shipped
Federal Surplus/Deficit badge (federal_deficit_client.py, FRED MTSDS133FMS):
the deficit badge is a flow/run-rate measure (how fast new debt is being
added this year), while this badge is a cumulative stock/ratio measure (how
large the total debt burden is relative to the size of the economy). Both
feed into the same fiscal-policy read-through but answer different
questions.

Positive-valued series (percent of GDP) -- unlike the deficit/trade-balance
badges, no sign-inversion needed: a higher ratio is unambiguously "rising"
debt burden, same as every other standard macro badge's _trend() shape.

Same free, keyless fredgraph.csv fetch pattern already proven for every
other FRED-sourced badge -- plain requests.get, never curl (documented
HTTP/2 stream-reset false-positive on this endpoint).
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GFDEGDQ188S"
_CACHE_TTL_S = 3600  # GFDEGDQ188S updates quarterly; hourly refetch is plenty
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
            print(f"[FederalDebtGDP] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[FederalDebtGDP] fetch error: {e}")
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


def compute_federal_debt_gdp() -> dict | None:
    """{"latest": float (percent of GDP), "date": str, "change_qoq": float,
    "trend_8q": {...}, "regime": "rising"/"falling"/"stable"} or None if the
    feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 9:
        return None

    values = [v for _, v in series]
    trend_8q = _trend(values[-9:])
    if trend_8q is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_qoq = latest_val - prev_val

    return {
        "latest": round(latest_val, 3),
        "date": latest_date,
        "change_qoq": round(change_qoq, 2),
        "trend_8q": trend_8q,
        "regime": trend_8q["direction"],
    }


def get_federal_debt_gdp(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_federal_debt_gdp()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
