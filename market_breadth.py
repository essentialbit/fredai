"""Market breadth -- equal-weight vs cap-weight S&P 500 concentration signal.

RSP (Invesco S&P 500 Equal Weight ETF) vs SPY: a falling RSP/SPY ratio while
SPY itself rises is a classic late-cycle warning sign (narrow leadership --
index gains concentrated in a handful of mega-cap names). Distinct from every
other shipped/proposed macro badge: VIX term structure is options-implied
vol, credit spread is the bond market, Copper/Gold is a commodity ratio,
sector rotation is relative strength across 11 sector ETFs vs SPY -- this
measures internal equity-market participation breadth specifically.

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
both RSP and SPY pay regular dividends, which crashes this dev environment's
pandas dividend tz-localize path, see project memory). Same Yahoo chart path
already used by copper_gold_ratio.py/sector_rotation.py/credit_spread.py.
"""
import statistics
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/sector_rotation.py
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/trend direction against the trailing
    window (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's _trend() helper."""
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


def compute_market_breadth() -> dict | None:
    """{"ratio": float, "change_5d_pct": float, "trend_20d": {...}, "regime"}
    (regime is "broad"/"narrowing"/"narrow", derived from the 20d rolling
    z-score direction), or None if either ETF's history can't be fetched."""
    rsp_history = fetch_history("RSP", period="1mo", interval="1d")
    spy_history = fetch_history("SPY", period="1mo", interval="1d")
    if not rsp_history or not spy_history:
        return None

    n = min(len(rsp_history), len(spy_history))
    rsp_closes = [r["close"] for r in rsp_history[-n:]]
    spy_closes = [r["close"] for r in spy_history[-n:]]
    ratio_series = [r / s for r, s in zip(rsp_closes, spy_closes) if s]
    if len(ratio_series) < 21:
        return None

    trend_20d = _trend(ratio_series)
    change_5d_pct = _period_change_pct(ratio_series, 5)
    if trend_20d is None or change_5d_pct is None:
        return None

    if trend_20d["direction"] == "rising":
        regime = "broad"
    elif trend_20d["direction"] == "falling":
        regime = "narrowing"
    else:
        regime = "neutral"

    return {
        "ratio": round(ratio_series[-1], 4),
        "change_5d_pct": round(change_5d_pct, 2),
        "trend_20d": trend_20d,
        "regime": regime,
    }


def get_market_breadth(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_market_breadth()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
