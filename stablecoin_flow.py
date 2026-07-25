"""Stablecoin net issuance flow (USDT+USDC combined market-cap velocity) --
crypto systemic liquidity leading indicator (FSI L5).

Combined USDT+USDC market cap tracks net new stablecoin minting/redemption,
which is a widely-used proxy for capital entering or leaving the crypto
ecosystem ahead of price moves -- distinct from the already-shipped Bitcoin
on-chain metrics (chain-level activity) and crypto Fear & Greed (sentiment)
signals. Rising combined cap = net issuance/inflow (risk-on capital
staging), falling = net redemption/outflow (risk-off deleveraging).

Uses CoinGecko's keyless `/coins/{id}/market_chart` endpoint (same free API
already used by market_data.py for crypto quotes) -- no auth required.
"""
import statistics
import time

import requests

_COINGECKO_MARKET_CHART = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
_CACHE_TTL_S = 1800  # 30 min -- stablecoin supply changes slowly, no need for tighter polling
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


def _fetch_market_caps(coin_id: str, days: int = 90) -> list[float] | None:
    try:
        r = requests.get(
            _COINGECKO_MARKET_CHART.format(coin_id=coin_id),
            params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
            timeout=15,
        )
        r.raise_for_status()
        caps = r.json().get("market_caps")
        if not caps:
            return None
        return [point[1] for point in caps]
    except Exception:
        return None


def compute_stablecoin_flow() -> dict | None:
    """{"combined_cap_usd": float, "change_7d_pct": float, "trend_30d": {...},
    "regime"} (regime is "inflow"/"outflow"/"neutral", derived from the 30d
    rolling z-score direction), or None if either stablecoin's history can't
    be fetched."""
    usdt_caps = _fetch_market_caps("tether")
    usdc_caps = _fetch_market_caps("usd-coin")
    if not usdt_caps or not usdc_caps:
        return None

    n = min(len(usdt_caps), len(usdc_caps))
    combined_series = [a + b for a, b in zip(usdt_caps[-n:], usdc_caps[-n:])]
    if len(combined_series) < 31:
        return None

    trend_30d = _trend(combined_series)
    change_7d_pct = _period_change_pct(combined_series, 7)
    if trend_30d is None or change_7d_pct is None:
        return None

    if trend_30d["direction"] == "rising":
        regime = "inflow"
    elif trend_30d["direction"] == "falling":
        regime = "outflow"
    else:
        regime = "neutral"

    return {
        "combined_cap_usd": round(combined_series[-1], 2),
        "change_7d_pct": round(change_7d_pct, 2),
        "trend_30d": trend_30d,
        "regime": regime,
    }


def get_stablecoin_flow(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_stablecoin_flow()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
