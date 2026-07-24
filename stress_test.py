"""Portfolio historical stress test — replay a user's actual current
holdings through two fixed past crisis windows (2020 COVID crash, 2022
rate-hike bear market) and report the hypothetical portfolio-level move.

Distinct from portfolio_risk.py (statistical VaR/Sharpe/max-drawdown over
the portfolio's own recent trading window, backward-looking) and from
backtesting_engine.py (signal prediction-accuracy tracking) — this answers
"what would happen to my exact holdings today if 2020 or 2022 repeated."

Pure Python by design, same budget reasoning as portfolio_risk.py. Reuses
market_data.fetch_history directly rather than portfolio_risk._daily_closes
since that cache is scoped to ~1y of bars — stress windows need 5y range.
"""

import time
from datetime import datetime

from market_data import fetch_history

STRESS_WINDOWS = {
    "covid_2020": {
        "label": "COVID Crash (Feb 19 - Mar 23, 2020)",
        "start_date": "2020-02-19",
        "end_date": "2020-03-23",
    },
    "bear_2022": {
        "label": "2022 Rate-Hike Bear Market (Jan 3 - Oct 13, 2022)",
        "start_date": "2022-01-03",
        "end_date": "2022-10-13",
    },
}

# A holding's own history must bracket the window within this many days on
# either side, or its data is treated as missing for that scenario rather
# than silently using a stale/unrelated price (MISSION.md Principle #7).
_MAX_BRACKET_SLACK_DAYS = 7

_HISTORY_TTL = 12 * 3600
_history_cache: dict[str, tuple[float, dict[str, float]]] = {}

_RESULT_TTL = 30 * 60
_result_cache: dict[int, tuple[float, dict]] = {}


def _daily_closes_5y(symbol: str) -> dict[str, float]:
    now = time.time()
    hit = _history_cache.get(symbol)
    if hit and now - hit[0] < _HISTORY_TTL:
        return hit[1]
    records = fetch_history(symbol, period="5y", interval="1d")
    closes = {r["time"][:10]: r["close"] for r in records if r.get("close")}
    if closes:
        _history_cache[symbol] = (now, closes)
    return closes


def _bracket_price(closes: dict[str, float], target_date: str, seek: str) -> float | None:
    """seek='forward': nearest close on or after target_date.
    seek='backward': nearest close on or before target_date."""
    dates = sorted(closes)
    if seek == "forward":
        candidates = [d for d in dates if d >= target_date]
        candidates.sort()
    else:
        candidates = [d for d in dates if d <= target_date]
        candidates.sort(reverse=True)
    if not candidates:
        return None
    picked = candidates[0]
    delta = abs((datetime.fromisoformat(picked) - datetime.fromisoformat(target_date)).days)
    if delta > _MAX_BRACKET_SLACK_DAYS:
        return None
    return closes[picked]


def _scenario_for_positions(positions: list[dict], total_value: float, window: dict) -> dict:
    start, end = window["start_date"], window["end_date"]
    weighted_sum = 0.0
    covered_weight = 0.0
    per_holding = []
    excluded = []

    for p in positions:
        sym = p["symbol"]
        closes = _daily_closes_5y(sym)
        start_price = _bracket_price(closes, start, "forward")
        end_price = _bracket_price(closes, end, "backward")
        if not closes or start_price is None or end_price is None or start_price <= 0:
            excluded.append(sym)
            continue
        pct_change = (end_price / start_price - 1.0) * 100
        weight = p["value"] / total_value
        weighted_sum += weight * pct_change
        covered_weight += weight
        per_holding.append({"symbol": sym, "pct_change": round(pct_change, 2)})

    if not per_holding:
        return {"status": "insufficient_history", "label": window["label"],
                "start_date": start, "end_date": end}

    # Renormalize to the covered slice so a couple of missing symbols don't
    # silently understate the move — but only if we actually covered most of
    # the book; otherwise the number would be more fiction than signal.
    if covered_weight < 0.5:
        return {"status": "insufficient_history", "label": window["label"],
                "start_date": start, "end_date": end,
                "holdings_covered": len(per_holding), "holdings_excluded": excluded}

    portfolio_pct = weighted_sum / covered_weight
    per_holding.sort(key=lambda h: h["pct_change"])

    return {
        "status": "ok",
        "label": window["label"],
        "start_date": start,
        "end_date": end,
        "portfolio_pct_change": round(portfolio_pct, 2),
        "portfolio_value_change": round(total_value * portfolio_pct / 100, 2),
        "worst_holding": per_holding[0],
        "best_holding": per_holding[-1],
        "holdings_covered": len(per_holding),
        "holdings_excluded": excluded,
        "coverage_pct": round(covered_weight * 100, 1),
    }


def compute_portfolio_stress_test(positions: list[dict], total_value: float | None = None) -> dict:
    """positions: [{symbol, value, ...}] as produced by calculate_portfolio_value."""
    positions = [p for p in positions if (p.get("value") or 0) > 0]
    if not positions:
        return {"status": "no_positions"}

    total = total_value or sum(p["value"] for p in positions)
    if total <= 0:
        return {"status": "no_positions"}

    scenarios = {
        key: _scenario_for_positions(positions, total, window)
        for key, window in STRESS_WINDOWS.items()
    }
    result = {
        "status": "ok",
        "as_of": datetime.utcnow().isoformat() + "Z",
        "scenarios": scenarios,
    }
    return result


def get_cached_stress_test(user_id: int, positions: list[dict], total_value: float | None = None) -> dict:
    now = time.time()
    hit = _result_cache.get(user_id)
    if hit and now - hit[0] < _RESULT_TTL:
        return hit[1]
    result = compute_portfolio_stress_test(positions, total_value)
    _result_cache[user_id] = (now, result)
    return result
