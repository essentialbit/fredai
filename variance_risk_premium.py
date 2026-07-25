"""Variance risk premium (VRP) -- gap between VIX (forward-looking implied
volatility) and SPY's own trailing realized volatility.

VIX normally sits above realized vol (option sellers earn a structural
premium for bearing tail risk); a collapsing or negative VRP is a
well-documented complacency/reversal warning. Distinct from the VIX
term-structure badge (#162, implied-vs-implied across maturities) and the
options put/call+IV tracker (#12, per-ticker single-name flow) -- this
compares implied to *realized* at the index level.

Uses market_data.fetch_history (never yfinance.Ticker.history directly --
SPY pays dividends, which crashes this dev environment's pandas dividend
tz-localize path, see project memory). Same Yahoo chart path already used by
copper_gold_ratio.py/market_breadth.py.
"""
import math
import statistics
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/market_breadth.py
_REALIZED_VOL_WINDOW = 21  # trailing daily closes -> 20 log returns
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


def _realized_vol_series(closes: list[float], window: int) -> list[float]:
    """Rolling annualized realized vol (stdev of daily log returns * sqrt(252) * 100)
    computed over a trailing `window`-close span for each point past the first window."""
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1]]
    series = []
    for i in range(window - 1, len(log_returns) + 1):
        chunk = log_returns[i - (window - 1):i]
        if len(chunk) < window - 1:
            continue
        series.append(statistics.pstdev(chunk) * math.sqrt(252) * 100)
    return series


def compute_variance_risk_premium() -> dict | None:
    """{"vrp": float, "vix": float, "realized_vol": float, "trend_20d": {...}, "regime"}
    (regime is "premium"/"compressed"/"inverted" off the VRP's own sign and
    rolling z-score), or None if either series can't be fetched."""
    spy_history = fetch_history("SPY", period="3mo", interval="1d")
    vix_history = fetch_history("^VIX", period="3mo", interval="1d")
    if not spy_history or not vix_history:
        return None

    spy_closes = [r["close"] for r in spy_history]
    vix_closes = [r["close"] for r in vix_history]
    realized_series = _realized_vol_series(spy_closes, _REALIZED_VOL_WINDOW)
    if not realized_series:
        return None

    n = min(len(realized_series), len(vix_closes))
    if n < 21:
        return None
    realized_series = realized_series[-n:]
    vix_aligned = vix_closes[-n:]
    vrp_series = [v - r for v, r in zip(vix_aligned, realized_series)]

    trend_20d = _trend(vrp_series)
    if trend_20d is None:
        return None

    latest_vrp = vrp_series[-1]
    if latest_vrp < 0:
        regime = "inverted"
    elif trend_20d["direction"] == "falling":
        regime = "compressed"
    else:
        regime = "premium"

    return {
        "vrp": round(latest_vrp, 2),
        "vix": round(vix_aligned[-1], 2),
        "realized_vol": round(realized_series[-1], 2),
        "trend_20d": trend_20d,
        "regime": regime,
    }


def get_variance_risk_premium(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_variance_risk_premium()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
