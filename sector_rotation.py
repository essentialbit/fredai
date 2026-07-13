"""Sector rotation / relative-strength ranking -- the 11 SPDR sector ETFs vs SPY.

Institutional sector-rotation signal (FSI L2): ranks each sector's 5-day and
20-day return spread against the SPY benchmark to surface rotation leaders
and laggards. Reuses market_data.fetch_history (the same Yahoo chart path
already used for SPY/QQQ elsewhere) -- no new library, no new external
endpoint, no yfinance.fast_info involved.
"""
import time

from market_data import fetch_history

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

_CACHE_TTL_S = 900  # 15 min -- 11 ETF history fetches per call is unnecessary load
_cache: dict = {"computed_at": 0.0, "data": None}


def _period_return_pct(history: list[dict], days: int) -> float | None:
    if len(history) < days + 1:
        return None
    start = history[-(days + 1)]["close"]
    end = history[-1]["close"]
    if not start:
        return None
    return (end - start) / start * 100


def compute_sector_rotation() -> list[dict]:
    """Ranked leader-to-laggard list of {symbol, name, return_5d, return_20d,
    relative_strength_5d, relative_strength_20d}, sorted by 20d relative
    strength descending. Empty if SPY's own history can't be fetched."""
    spy_history = fetch_history("SPY", period="1mo", interval="1d")
    spy_5d = _period_return_pct(spy_history, 5)
    spy_20d = _period_return_pct(spy_history, 20)
    if spy_5d is None or spy_20d is None:
        return []

    rows = []
    for symbol, name in SECTOR_ETFS.items():
        history = fetch_history(symbol, period="1mo", interval="1d")
        r5 = _period_return_pct(history, 5)
        r20 = _period_return_pct(history, 20)
        if r5 is None or r20 is None:
            continue
        rows.append({
            "symbol": symbol,
            "name": name,
            "return_5d": round(r5, 2),
            "return_20d": round(r20, 2),
            "relative_strength_5d": round(r5 - spy_5d, 2),
            "relative_strength_20d": round(r20 - spy_20d, 2),
        })

    rows.sort(key=lambda r: r["relative_strength_20d"], reverse=True)
    return rows


def get_sector_rotation(force: bool = False) -> list[dict]:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_sector_rotation()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"] or []
