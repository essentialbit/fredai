"""CBOE VVIX Index -- volatility-of-volatility tail-risk hedging badge.

VVIX measures the implied volatility of VIX options themselves, distinct
from VIX (implied vol of the S&P 500) and from VIX term structure (implied
vol across maturities). A rising VVIX signals growing demand for tail-risk
/ VIX-option hedging, often leading broader market stress.

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
see project memory re: pandas dividend tz-localize crashes; ^VVIX pays no
dividend but every other macro badge already standardized on this path).
"""
import statistics
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/credit_spread.py
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Same shape as copper_gold_ratio.py's _trend() helper: latest value +
    rolling z-score/direction against the trailing window, excluding the
    latest point from its own baseline."""
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
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def _classify_regime(value: float) -> str:
    """Absolute bands per the issue spec (Normal < 90, Elevated 90-110, High Stress > 110)
    -- VVIX is construction-normalized around these historical levels, same
    justification used for epu_index.py's absolute banding."""
    if value < 90:
        return "normal"
    if value <= 110:
        return "elevated"
    return "high_stress"


def compute_vvix_index() -> dict | None:
    """{"value": float, "trend_90d": {...}, "regime": "normal"/"elevated"/"high_stress"}
    or None if history can't be fetched / insufficient points."""
    history = fetch_history("^VVIX", period="6mo", interval="1d")
    if not history:
        return None

    closes = [r["close"] for r in history]
    if len(closes) < 21:
        return None

    window = closes[-90:] if len(closes) >= 90 else closes
    trend_90d = _trend(window)
    if trend_90d is None:
        return None

    return {
        "value": round(closes[-1], 2),
        "trend_90d": trend_90d,
        "regime": _classify_regime(closes[-1]),
    }


def get_vvix_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_vvix_index()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
