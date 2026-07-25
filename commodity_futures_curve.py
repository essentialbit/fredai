"""Commodity futures curve -- contango/backwardation signal (FSI L3).

Tracks WTI crude oil and gold contract-month futures prices via the app's
existing direct-Yahoo-chart-endpoint pattern (same trust boundary as every
other macro-strip badge's read-only market data). A rising price further out
the curve is contango (oversupply/storage-cost carry); a falling price
further out is backwardation (near-term supply tightness). Distinct from
#162's VIX term structure, which is an implied-volatility curve, not a
physical-commodity price curve.

Uses market_data.fetch_history (the direct chart-endpoint wrapper), never
yfinance.Ticker.history -- see project memory on the pandas dividend
tz-localize crash for dividend-paying tickers (contracts here pay none, but
the direct-endpoint path is the proven-safe convention regardless).
"""
import statistics
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/credit_spread.py

_BASKETS = {
    "WTI_CRUDE": ["CLZ26.NYM", "CLF27.NYM", "CLM27.NYM", "CLZ27.NYM"],
    "GOLD": ["GCZ26.CMX", "GCM27.CMX"],
}

_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Same shape as copper_gold_ratio.py's _trend() -- rolling z-score of the
    latest point against the trailing window, excluding the point itself."""
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


def fetch_curve(contracts: list[str]) -> list[dict]:
    """Latest close for each contract-month ticker, in curve order.
    Skips any contract whose history can't be fetched (Yahoo rate-limit,
    delisted/rolled contract, etc.) rather than failing the whole basket."""
    points = []
    for ticker in contracts:
        history = fetch_history(ticker, period="5d", interval="1d")
        if not history:
            continue
        points.append({"contract": ticker, "price": history[-1]["close"]})
    return points


def compute_curve_slope(prices: list[dict]) -> dict | None:
    """Classifies the curve from the front-to-back percentage spread between
    the nearest and furthest available contracts. Needs at least 2 points."""
    if len(prices) < 2:
        return None
    front, back = prices[0]["price"], prices[-1]["price"]
    if not front:
        return None
    spread_pct = (back - front) / front * 100
    if spread_pct > 0.5:
        classification = "contango"
    elif spread_pct < -0.5:
        classification = "backwardation"
    else:
        classification = "flat"
    return {
        "front_contract": prices[0]["contract"],
        "back_contract": prices[-1]["contract"],
        "front_price": round(front, 2),
        "back_price": round(back, 2),
        "spread_pct": round(spread_pct, 2),
        "classification": classification,
    }


def _basket_history_series(contracts: list[str]) -> list[float]:
    """Trailing daily front-to-back spread-pct series for the z-score trend,
    built from each contract's own trailing daily closes (front/back fixed to
    the same two tickers used in the live curve read)."""
    front_hist = fetch_history(contracts[0], period="1mo", interval="1d")
    back_hist = fetch_history(contracts[-1], period="1mo", interval="1d")
    if not front_hist or not back_hist:
        return []
    n = min(len(front_hist), len(back_hist))
    series = []
    for f, b in zip(front_hist[-n:], back_hist[-n:]):
        if f["close"]:
            series.append((b["close"] - f["close"]) / f["close"] * 100)
    return series


def compute_basket(contracts: list[str]) -> dict | None:
    prices = fetch_curve(contracts)
    slope = compute_curve_slope(prices)
    if slope is None:
        return None
    series = _basket_history_series(contracts)
    trend_20d = _trend(series) if series else None
    return {**slope, "curve": prices, "trend_20d": trend_20d}


def compute_commodity_futures_curve() -> dict | None:
    """{"WTI_CRUDE": {...}, "GOLD": {...}}, or None if neither basket has
    enough live data."""
    result = {}
    for name, contracts in _BASKETS.items():
        basket = compute_basket(contracts)
        if basket:
            result[name] = basket
    return result or None


def most_extreme_basket(data: dict) -> dict | None:
    """The basket with the largest |spread_pct|, for the single-value
    macro-strip badge slot."""
    if not data:
        return None
    name, basket = max(data.items(), key=lambda kv: abs(kv[1]["spread_pct"]))
    return {"name": name, **basket}


def get_commodity_futures_curve(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_commodity_futures_curve()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
