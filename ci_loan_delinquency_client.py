"""Commercial & Industrial (C&I) Loan Delinquency Rate (FRED DRBLACBS) --
quarterly business/corporate credit-quality macro badge.

Federal Reserve series for the delinquency rate on business loans (C&I
lending) held by all commercial banks -- the share of business-loan
balances 30+ days past due. Distinct from the Commercial Real Estate
delinquency badge (property-collateralized loans): this tracks general
business/working-capital lending, a different credit channel and an
independent leading indicator of corporate distress.

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

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DRBLACBS"
_CACHE_TTL_S = 21600  # DRBLACBS updates quarterly; 6h refetch is plenty


_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Higher delinquency is already plain-language "worse", so no sign
    inversion is needed -- unlike a negative-valued deficit series,
    DRBLACBS reads naturally."""
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
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[CILoanDelinquency] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[CILoanDelinquency] fetch error: {e}")
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


def compute_ci_loan_delinquency() -> dict | None:
    """{"latest": float (percent), "date": str, "change_q1_pct": float,
    "trend_20q": {...}, "regime": "rising"/"falling"/"stable"} or None if the
    feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    trend_20q = _trend(values[-20:])
    if trend_20q is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    change_q1_pct = (latest_val - prev_val) / prev_val * 100 if prev_val else None

    return {
        "latest": round(latest_val, 2),
        "date": latest_date,
        "change_q1_pct": round(change_q1_pct, 2) if change_q1_pct is not None else None,
        "trend_20q": trend_20q,
        "regime": trend_20q["direction"],
    }


def get_ci_loan_delinquency(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_ci_loan_delinquency()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
