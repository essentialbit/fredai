"""Fed balance sheet (WALCL) / M2 money supply (M2SL) liquidity regime badge.

WALCL = Fed System Open Market Account total assets, weekly. A growing
balance sheet is QE-like easing (the Fed is expanding liquidity); a shrinking
one is QT-like tightening. M2SL = M2 money supply, monthly, the broader
liquidity aggregate. Distinct from #103 (broad multi-indicator macro regime
detector, still risk:high/blocked) -- this is a single narrow liquidity
signal with zero external dependency, same scoping pattern as the
yield-curve/jobless-claims/EPU/breakeven-inflation badges.

Same free fredgraph.csv fetch (no API key, no signup) already used by
breakeven_inflation.py/jobless_claims_client.py.
"""
import csv
import io
import time

import requests

_WALCL_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL"
_M2SL_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL"
_CACHE_TTL_S = 43200  # weekly/monthly series -- 12h refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}

_EASE_THRESHOLD = 0.15   # % change threshold to call a series "expanding"
_TIGHTEN_THRESHOLD = -0.15  # % change threshold to call a series "contracting"


def fetch_series(url: str) -> list[tuple[str, float]] | None:
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"[FedLiquidity] HTTP {r.status_code} for {url}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[FedLiquidity] fetch error: {e}")
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


def _pct_change(series: list[tuple[str, float]], periods_back: int) -> float | None:
    if len(series) <= periods_back:
        return None
    latest = series[-1][1]
    prior = series[-1 - periods_back][1]
    if prior == 0:
        return None
    return round((latest - prior) / abs(prior) * 100, 3)


def _classify(pct_change: float) -> str:
    if pct_change > _EASE_THRESHOLD:
        return "expanding"
    if pct_change < _TIGHTEN_THRESHOLD:
        return "contracting"
    return "flat"


def compute_liquidity_snapshot() -> dict | None:
    """{"walcl": {...}, "m2sl": {...}, "regime": "easing"/"tightening"/"neutral"}
    or None if either feed can't be fetched or has too little history."""
    walcl = fetch_series(_WALCL_URL)
    m2sl = fetch_series(_M2SL_URL)
    if not walcl or len(walcl) < 2 or not m2sl or len(m2sl) < 2:
        return None

    walcl_chg = _pct_change(walcl, 1)  # weekly series -> 1 period = 1 week
    m2sl_chg = _pct_change(m2sl, 1)  # monthly series -> 1 period = 1 month
    if walcl_chg is None or m2sl_chg is None:
        return None

    walcl_state = _classify(walcl_chg)
    m2sl_state = _classify(m2sl_chg)

    if walcl_state == "expanding" and m2sl_state != "contracting":
        regime = "easing"
    elif walcl_state == "contracting" and m2sl_state != "expanding":
        regime = "tightening"
    else:
        regime = "neutral"

    return {
        "walcl": {"latest": walcl[-1][1], "date": walcl[-1][0], "change_wow_pct": walcl_chg, "state": walcl_state},
        "m2sl": {"latest": m2sl[-1][1], "date": m2sl[-1][0], "change_mom_pct": m2sl_chg, "state": m2sl_state},
        "regime": regime,
    }


def get_liquidity_snapshot(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_liquidity_snapshot()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
