"""Kalshi KXPAYROLLS threshold ladder -- market-implied median Non-Farm
Payrolls forecast ahead of the BLS print.

Distinct from every already-shipped labor-market signal (jobless claims
trend, job-listing hiring velocity, Sahm Rule): those all react to data
that has already been released, while this is a real-money crowd forecast
of the NEXT print. Same public Kalshi list-markets endpoint already shipped
in fed_decision_market.py (#257/PR #258) -- no key or account needed.

KXPAYROLLS is a threshold ladder, not a discrete outcome set like
KXFEDDECISION: each event (one per release month) has several markets
("Above 90,000 jobs added", "Above 80,000", ...), each resolving Yes/No
independently against the same print. `last_price_dollars` is the
market-implied probability that the print exceeds that rung's
`floor_strike`, monotonically decreasing as the strike rises. Linearly
interpolating between the two adjacent rungs that straddle 0.5 gives a
market-implied median NFP forecast in thousands of jobs.
"""
import time

import requests

_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
_SERIES_TICKER = "KXPAYROLLS"
_MIN_OPEN_INTEREST = 100  # degrade (omit badge) below this, same floor as fed_decision_market.py

_CACHE_TTL_S = 3600  # 1h -- ladder odds move on macro data, not intraday noise
_cache: dict = {"computed_at": 0.0, "data": None}


def _fetch_open_markets() -> list[dict]:
    markets: list[dict] = []
    cursor = None
    for _ in range(10):
        params = {"series_ticker": _SERIES_TICKER, "status": "open", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(_MARKETS_URL, params=params, timeout=15)
        if r.status_code != 200:
            break
        data = r.json()
        markets.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return markets


def _interpolate_median_strike(rungs: list[dict]) -> float | None:
    """rungs sorted ascending by floor_strike. Find the two adjacent rungs whose
    implied Yes probability straddles 0.5 and linearly interpolate the strike
    where probability == 0.5. None if the ladder never crosses 0.5 (degenerate)."""
    for i in range(len(rungs) - 1):
        hi_prob, lo_prob = rungs[i]["prob"], rungs[i + 1]["prob"]
        if hi_prob == 0.5:
            return rungs[i]["floor_strike"]
        if hi_prob > 0.5 >= lo_prob and hi_prob != lo_prob:
            hi_strike, lo_strike = rungs[i]["floor_strike"], rungs[i + 1]["floor_strike"]
            frac = (hi_prob - 0.5) / (hi_prob - lo_prob)
            return hi_strike + frac * (lo_strike - hi_strike)
    if rungs and rungs[-1]["prob"] == 0.5:
        return rungs[-1]["floor_strike"]
    return None


def compute_payrolls_consensus() -> dict | None:
    """{"implied_median_k": float, "release_date": "YYYY-MM-DD", "open_interest": int}
    or None if there's no eligible nearest event / the ladder doesn't cross 0.5."""
    try:
        markets = _fetch_open_markets()
    except Exception as e:
        print(f"[PayrollsConsensusMarket] fetch error: {e}")
        return None
    if not markets:
        return None

    events: dict[str, list[dict]] = {}
    for m in markets:
        events.setdefault(m["event_ticker"], []).append(m)

    nearest_event = min(events.values(), key=lambda ms: min(m["close_time"] for m in ms))
    open_interest = sum(float(m.get("open_interest_fp", 0) or 0) for m in nearest_event)
    if open_interest < _MIN_OPEN_INTEREST:
        return None

    rungs = []
    for m in nearest_event:
        try:
            rungs.append({
                "floor_strike": float(m["floor_strike"]),
                "prob": float(m["last_price_dollars"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    rungs.sort(key=lambda r: r["floor_strike"])
    if len(rungs) < 2:
        return None

    median_strike = _interpolate_median_strike(rungs)
    if median_strike is None:
        return None

    release_date = min(m["close_time"] for m in nearest_event)[:10]

    return {
        "implied_median_k": round(median_strike / 1000, 1),
        "release_date": release_date,
        "open_interest": int(open_interest),
    }


def get_payrolls_consensus(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_payrolls_consensus()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
