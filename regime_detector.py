"""Per-ticker technical regime classifier (ADX) -- trending vs range-bound.

Distinct from #103's macroeconomic regime taxonomy (inflation/growth cycle
classification): this is a per-ticker technical price-action regime, computed
purely from already-fetched OHLC history via market_data.fetch_history(), no
new external data source or API key needed.

ADX (Average Directional Index, Wilder smoothing) measures trend strength
regardless of direction: ADX >= 25 reads trending, ADX < 20 reads
range-bound/mean-reverting, the band between is transitional. Used by
technical_alerts.py to weight which alert types are more actionable in the
current regime (breakout-style MA crosses in trending markets, RSI
overbought/oversold in range-bound markets).
"""
from __future__ import annotations

import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/sector_rotation.py
_cache: dict[str, dict] = {}


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    smoothed = [sum(values[:period])]
    for v in values[period:]:
        smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
    return smoothed


def compute_adx(candles: list[dict], period: int = 14) -> float | None:
    """Wilder's ADX from a list of {"high","low","close"} candles, oldest first."""
    if len(candles) < period * 2 + 1:
        return None

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, len(candles)):
        high, low, prev_close = highs[i], lows[i], closes[i - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        trs.append(tr)
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    if len(trs) < period * 2:
        return None

    smoothed_tr = _wilder_smooth(trs, period)
    smoothed_plus_dm = _wilder_smooth(plus_dms, period)
    smoothed_minus_dm = _wilder_smooth(minus_dms, period)

    dx_values = []
    for tr, pdm, mdm in zip(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm):
        if tr == 0:
            continue
        plus_di = 100 * pdm / tr
        minus_di = 100 * mdm / tr
        di_sum = plus_di + minus_di
        dx_values.append(100 * abs(plus_di - minus_di) / di_sum if di_sum else 0.0)

    if len(dx_values) < period:
        return None

    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period

    return round(adx, 2)


def classify_regime(adx: float | None) -> str:
    if adx is None:
        return "unknown"
    if adx >= 25:
        return "trending"
    if adx < 20:
        return "ranging"
    return "transitional"


def compute_regime(symbol: str) -> dict | None:
    candles = fetch_history(symbol, period="3mo", interval="1d")
    if not candles:
        return None
    adx = compute_adx(candles, period=14)
    return {"symbol": symbol, "adx": adx, "regime": classify_regime(adx)}


def get_regime(symbol: str, force: bool = False) -> dict | None:
    """TTL-cached per-symbol accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    entry = _cache.get(symbol)
    if not force and entry and now - entry["computed_at"] < _CACHE_TTL_S:
        return entry["data"]
    data = compute_regime(symbol)
    if data:
        _cache[symbol] = {"computed_at": now, "data": data}
        return data
    return entry["data"] if entry else None
