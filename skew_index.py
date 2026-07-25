"""CBOE SKEW Index -- tail-risk gauge macro-strip badge.

VIX prices near-term at-the-money S&P 500 option volatility (broad fear
gauge). SKEW is derived from out-of-the-money option pricing and measures
the market-implied probability of a tail-risk / black-swan move. The two
can diverge: low VIX with elevated SKEW is a known pattern preceding sharp
drawdowns (complacent broad market, but rising crash-insurance demand).

Distinct from options_max_pain's per-ticker single-name IV skew -- this is
a single market-wide index series, same shape as the already-shipped
VIX term structure / credit spread / copper-gold badges.

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
see project memory re: the dividend tz-localize crash; ^SKEW is an index,
not dividend-paying, but stay consistent with the established safe path).
"""
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/credit_spread.py
_cache: dict = {"computed_at": 0.0, "data": None}

# Bands per S&P Global public SKEW methodology.
_ELEVATED_THRESHOLD = 135
_EXTREME_THRESHOLD = 150


def _classify(value: float) -> str:
    if value > _EXTREME_THRESHOLD:
        return "extreme"
    if value > _ELEVATED_THRESHOLD:
        return "elevated"
    return "normal"


def _period_change_pct(series: list[float], days: int) -> float | None:
    if len(series) < days + 1:
        return None
    start, end = series[-(days + 1)], series[-1]
    if not start:
        return None
    return (end - start) / start * 100


def compute_skew_index() -> dict | None:
    """{"value": float, "band": "normal"/"elevated"/"extreme", "change_5d_pct": float}
    or None if the ^SKEW history can't be fetched."""
    history = fetch_history("^SKEW", period="1mo", interval="1d")
    if not history or len(history) < 6:
        return None

    closes = [r["close"] for r in history]
    latest = closes[-1]
    change_5d_pct = _period_change_pct(closes, 5)

    return {
        "value": round(latest, 2),
        "band": _classify(latest),
        "change_5d_pct": round(change_5d_pct, 2) if change_5d_pct is not None else None,
    }


def get_skew_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_skew_index()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
