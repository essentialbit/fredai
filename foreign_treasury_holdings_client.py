"""Foreign Holdings of US Treasury Debt (FRED FDHBFIN) -- geopolitical
capital-flow demand-signal macro badge (FSI L2, closes #481).

Federal Debt Held by Foreign and International Investors, published
quarterly by the US Treasury/Fed (Financial Accounts of the United States,
Z.1). Genuinely distinct from the existing fiscal badges: FEDERAL_DEBT_GDP
tracks the total debt burden relative to the economy (how large the debt
is), while this tracks who holds a portion of that debt and whether foreign
demand for it is rising or falling -- a dedollarization/reserve-diversification
and safe-haven-demand read that neither FEDERAL_DEBT_GDP nor
TREASURY_AUCTION (primary-market bid-to-cover, not the stock of
already-issued foreign-held debt) captures.

Positive-valued series (USD billions) -- no sign-inversion needed, unlike
the deficit/trade-balance badges: a rising level is unambiguously "rising"
foreign demand, same standard _trend() shape as every other macro badge.

Same free, keyless fredgraph.csv fetch pattern already proven for every
other FRED-sourced badge -- plain requests.get, never curl.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FDHBFIN"
_CACHE_TTL_S = 3600  # FDHBFIN updates quarterly; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as federal_debt_gdp_client.py/durable_goods_client.py's _trend()."""
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
            print(f"[ForeignTreasuryHoldings] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[ForeignTreasuryHoldings] fetch error: {e}")
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


def compute_foreign_treasury_holdings() -> dict | None:
    """{"latest_trillions": float, "date": str, "change_qoq_trillions": float,
    "trend_8q": {...}, "regime": "rising"/"falling"/"stable"} or None if the
    feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 9:
        return None

    values = [v for _, v in series]  # USD billions
    trend_8q = _trend(values[-9:])
    if trend_8q is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]

    return {
        "latest_trillions": round(latest_val / 1000, 3),
        "date": latest_date,
        "change_qoq_trillions": round((latest_val - prev_val) / 1000, 3),
        "trend_8q": trend_8q,
        "regime": trend_8q["direction"],
    }


def get_foreign_treasury_holdings(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_foreign_treasury_holdings()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
