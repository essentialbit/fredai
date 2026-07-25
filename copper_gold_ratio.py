"""Copper/Gold ratio ("Dr. Copper") -- cross-asset growth-vs-safe-haven
regime signal.

Copper demand tracks industrial/construction activity while gold tracks
safe-haven flows, so the CPER/GLD ratio is a well-known macro leading
indicator: a rising ratio reads risk-on/reflationary, a falling ratio reads
risk-off/growth-scare. Distinct from the already-shipped VIX term structure
(equity-option-implied vol) and credit spread (corporate bond market) signals.

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
both underlying commodities ETFs have crashed this dev environment's pandas
dividend tz-localize path before, see project memory). Same Yahoo chart path
already used by sector_rotation.py and credit_spread.py.
"""
import statistics
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching sector_rotation.py/credit_spread.py
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/trend direction against the trailing
    window (excluding the latest point, so the z-score isn't self-referential).
    Same shape as bitcoin_onchain_client.py's _trend() helper."""
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


def _period_change_pct(series: list[float], days: int) -> float | None:
    if len(series) < days + 1:
        return None
    start, end = series[-(days + 1)], series[-1]
    if not start:
        return None
    return (end - start) / start * 100


def compute_copper_gold_ratio() -> dict | None:
    """{"ratio": float, "change_5d_pct": float, "trend_20d": {...}, "regime"}
    (regime is "risk_on"/"risk_off"/"neutral", derived from the 20d rolling
    z-score direction), or None if either ETF's history can't be fetched."""
    cper_history = fetch_history("CPER", period="1mo", interval="1d")
    gld_history = fetch_history("GLD", period="1mo", interval="1d")
    if not cper_history or not gld_history:
        return None

    n = min(len(cper_history), len(gld_history))
    cper_closes = [r["close"] for r in cper_history[-n:]]
    gld_closes = [r["close"] for r in gld_history[-n:]]
    ratio_series = [c / g for c, g in zip(cper_closes, gld_closes) if g]
    if len(ratio_series) < 21:
        return None

    trend_20d = _trend(ratio_series)
    change_5d_pct = _period_change_pct(ratio_series, 5)
    if trend_20d is None or change_5d_pct is None:
        return None

    if trend_20d["direction"] == "rising":
        regime = "risk_on"
    elif trend_20d["direction"] == "falling":
        regime = "risk_off"
    else:
        regime = "neutral"

    return {
        "ratio": round(ratio_series[-1], 4),
        "change_5d_pct": round(change_5d_pct, 2),
        "trend_20d": trend_20d,
        "regime": regime,
    }


def get_copper_gold_ratio(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_copper_gold_ratio()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
