"""Credit spread proxy -- HYG (high-yield corporate) vs LQD (investment-grade
corporate) relative strength as a market-wide credit-stress signal.

Corporate credit markets historically lead equity drawdowns (2007-08, March
2020) by widening before risk-off shows up in VIX or equity price action.
This is distinct from vix_term_structure.py (equity-option-implied vol) and
from the macro regime detector (#103, FRED CPI/PMI series).

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
both HYG and LQD pay regular distributions and reliably crash this dev
environment's pandas dividend tz-localize path, see project memory). Same
Yahoo chart path already used by sector_rotation.py and correlation_engine.py.
"""
import time

from market_data import fetch_history

_WIDENING_THRESHOLD_PCT = -1.0  # HYG underperforms LQD by 1%+ -- credit stress
_NARROWING_THRESHOLD_PCT = 1.0

_CACHE_TTL_S = 900  # 15 min, matching sector_rotation.py's TTL
_cache: dict = {"computed_at": 0.0, "data": None}


def _period_return_pct(history: list[dict], days: int) -> float | None:
    if len(history) < days + 1:
        return None
    start = history[-(days + 1)]["close"]
    end = history[-1]["close"]
    if not start:
        return None
    return (end - start) / start * 100


def compute_credit_spread() -> dict | None:
    """{"hyg_return_5d", "lqd_return_5d", "spread_5d", "hyg_return_20d",
    "lqd_return_20d", "spread_20d", "regime"} (regime is "widening"/
    "narrowing"/"flat"), or None if either ETF's history can't be fetched."""
    hyg_history = fetch_history("HYG", period="1mo", interval="1d")
    lqd_history = fetch_history("LQD", period="1mo", interval="1d")

    hyg_5d, hyg_20d = _period_return_pct(hyg_history, 5), _period_return_pct(hyg_history, 20)
    lqd_5d, lqd_20d = _period_return_pct(lqd_history, 5), _period_return_pct(lqd_history, 20)
    if None in (hyg_5d, hyg_20d, lqd_5d, lqd_20d):
        return None

    spread_5d = hyg_5d - lqd_5d
    spread_20d = hyg_20d - lqd_20d
    if spread_20d <= _WIDENING_THRESHOLD_PCT:
        regime = "widening"
    elif spread_20d >= _NARROWING_THRESHOLD_PCT:
        regime = "narrowing"
    else:
        regime = "flat"

    return {
        "hyg_return_5d": round(hyg_5d, 2),
        "lqd_return_5d": round(lqd_5d, 2),
        "spread_5d": round(spread_5d, 2),
        "hyg_return_20d": round(hyg_20d, 2),
        "lqd_return_20d": round(lqd_20d, 2),
        "spread_20d": round(spread_20d, 2),
        "regime": regime,
    }


def get_credit_spread(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_credit_spread()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
