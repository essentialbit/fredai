"""Kalshi FOMC-decision prediction market -- real-money aggregated probability
distribution over the next Fed rate decision.

Distinct from the futures-curve proposal (#248, CME/Yahoo-sourced, repeatedly
blocked by rate-limiting): this is an independent public data source, Kalshi's
`KXFEDDECISION-*` event series (no key or account needed for market-data reads).

Feasibility-probed live 2026-07-13: the list-markets endpoint
(`/markets?series_ticker=KXFEDDECISION&status=open`) returns real, populated
`last_price_dollars`/`open_interest_fp` fields for the nearest event
(`KXFEDDECISION-26JUL`, Jul 29 2026 meeting, multi-million open interest) --
no need for the slower per-market single-ticker endpoint for this series.
"""
import time

import requests

_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
_SERIES_TICKER = "KXFEDDECISION"
_MIN_OPEN_INTEREST = 100  # degrade (omit badge) below this, same floor as other alt-data badges

_CACHE_TTL_S = 3600  # 1h -- odds move on macro data/Fed commentary, not intraday noise
_cache: dict = {"computed_at": 0.0, "data": None}

_SUFFIX_TO_OUTCOME = {
    "H0": "hold",
    "H25": "hike_25bp",
    "H26": "hike_gt25bp",
    "C25": "cut_25bp",
    "C26": "cut_gt25bp",
}

_OUTCOME_LABEL = {
    "hold": "hold",
    "hike_25bp": "hike 25bp",
    "hike_gt25bp": "hike >25bp",
    "cut_25bp": "cut 25bp",
    "cut_gt25bp": "cut >25bp",
}


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


def compute_fed_decision_odds() -> dict | None:
    """{"hold": float, "cut_25bp": float, "cut_gt25bp": float, "hike_25bp": float,
    "hike_gt25bp": float, "dominant": str, "meeting_date": "YYYY-MM-DD",
    "open_interest": int} or None if no eligible nearest event."""
    try:
        markets = _fetch_open_markets()
    except Exception as e:
        print(f"[FedDecisionMarket] fetch error: {e}")
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

    odds: dict[str, float] = {}
    for m in nearest_event:
        suffix = m["ticker"].rsplit("-", 1)[-1]
        outcome = _SUFFIX_TO_OUTCOME.get(suffix)
        if not outcome:
            continue
        try:
            odds[outcome] = float(m["last_price_dollars"])
        except (TypeError, ValueError):
            continue

    if "hold" not in odds:
        return None

    dominant = max(odds, key=odds.get)
    meeting_date = min(m["close_time"] for m in nearest_event)[:10]

    return {
        **{k: round(v, 4) for k, v in odds.items()},
        "dominant": dominant,
        "dominant_label": _OUTCOME_LABEL[dominant],
        "meeting_date": meeting_date,
        "open_interest": int(open_interest),
    }


def get_fed_decision_odds(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_fed_decision_odds()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
