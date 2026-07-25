"""Supply-chain stress proxy -- BDRY (Breakwave Dry Bulk Shipping ETF, tracks
Baltic Dry Index freight-rate futures) vs SPY relative strength.

Baltic Dry Index spikes/collapses have historically led broader freight,
inflation, and consumer-demand narratives by several weeks -- MISSION.md's
L5 "Supply chain stress indicators (Baltic Dry Index, container shipping
rates)" item. Distinct from vix_term_structure.py (equity-option-implied
vol) and credit_spread.py (corporate credit stress).

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
see project memory on the dividend tz-localize crash). Same Yahoo chart
path already used by sector_rotation.py and credit_spread.py.
"""
import time

from market_data import fetch_history

_STRESS_THRESHOLD_PCT = -10.0  # BDRY underperforms SPY by 10%+ -- sharp freight-rate collapse
_SPIKE_THRESHOLD_PCT = 10.0  # BDRY outperforms SPY by 10%+ -- sharp freight-rate spike

_CACHE_TTL_S = 900  # 15 min, matching sector_rotation.py/credit_spread.py's TTL
_cache: dict = {"computed_at": 0.0, "data": None}


def _period_return_pct(history: list[dict], days: int) -> float | None:
    if len(history) < days + 1:
        return None
    start = history[-(days + 1)]["close"]
    end = history[-1]["close"]
    if not start:
        return None
    return (end - start) / start * 100


def compute_supply_chain_stress() -> dict | None:
    """{"bdry_return_5d", "spy_return_5d", "spread_5d", "bdry_return_20d",
    "spy_return_20d", "spread_20d", "regime"} (regime is "stress"/"spike"/
    "normal"), or None if either ticker's history can't be fetched."""
    bdry_history = fetch_history("BDRY", period="1mo", interval="1d")
    spy_history = fetch_history("SPY", period="1mo", interval="1d")

    bdry_5d, bdry_20d = _period_return_pct(bdry_history, 5), _period_return_pct(bdry_history, 20)
    spy_5d, spy_20d = _period_return_pct(spy_history, 5), _period_return_pct(spy_history, 20)
    if None in (bdry_5d, bdry_20d, spy_5d, spy_20d):
        return None

    spread_5d = bdry_5d - spy_5d
    spread_20d = bdry_20d - spy_20d
    if spread_20d <= _STRESS_THRESHOLD_PCT:
        regime = "stress"
    elif spread_20d >= _SPIKE_THRESHOLD_PCT:
        regime = "spike"
    else:
        regime = "normal"

    return {
        "bdry_return_5d": round(bdry_5d, 2),
        "spy_return_5d": round(spy_5d, 2),
        "spread_5d": round(spread_5d, 2),
        "bdry_return_20d": round(bdry_20d, 2),
        "spy_return_20d": round(spy_20d, 2),
        "spread_20d": round(spread_20d, 2),
        "regime": regime,
    }


def get_supply_chain_stress(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_supply_chain_stress()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
