"""Crypto Conditions Index (CCI) -- combines the already-shipped Alternative.me
Crypto Fear & Greed value (see crypto_fear_greed.py) with a new BTC/ETH spot
volume-momentum signal from CoinGecko's free public API. Distinct from the
plain CRYPTO_FNG badge: that badge surfaces sentiment alone, this one blends
sentiment with whether trading volume itself is expanding or contracting,
which is what separates a genuine regime shift from sentiment noise (e.g. a
"greed" reading on shrinking volume is a weaker signal than one on expanding
volume).

No signup/key required: https://api.coingecko.com/api/v3/coins/{id}/market_chart
"""
import time

from copper_gold_ratio import _trend
from crypto_fear_greed import get_crypto_fear_greed

import requests

_VOLUME_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
_COINS = ("bitcoin", "ethereum")
_CACHE_TTL_S = 3600
_cache: dict = {"computed_at": 0.0, "data": None}


def _daily_volume_series(coin_id: str) -> list[float] | None:
    """CoinGecko returns hourly-granularity points for a 30-day window;
    downsample to one value (last-seen) per calendar day, oldest-first."""
    try:
        r = requests.get(
            _VOLUME_URL.format(coin_id=coin_id),
            params={"vs_currency": "usd", "days": 30},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[CryptoConditions] {coin_id} HTTP {r.status_code}")
            return None
        points = r.json().get("total_volumes", [])
    except Exception as e:
        print(f"[CryptoConditions] {coin_id} fetch error: {e}")
        return None
    if not points:
        return None

    by_day: dict[str, float] = {}
    for ms, vol in points:
        day = time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
        by_day[day] = vol  # last value seen for the day wins
    return [by_day[day] for day in sorted(by_day)]


def _volume_trend() -> dict | None:
    """Average the BTC/ETH volume z-score trends into one combined read."""
    trends = []
    for coin_id in _COINS:
        series = _daily_volume_series(coin_id)
        if not series:
            continue
        t = _trend(series)
        if t:
            trends.append(t)
    if not trends:
        return None
    avg_z = round(sum(t["z_score"] for t in trends) / len(trends), 2)
    if avg_z > 0.5:
        direction = "rising"
    elif avg_z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"z_score": avg_z, "direction": direction}


def _classify(score: float) -> str:
    if score <= 25:
        return "extreme fear"
    if score <= 45:
        return "fear"
    if score <= 55:
        return "neutral"
    if score <= 75:
        return "greed"
    return "extreme greed"


def compute_crypto_conditions() -> dict | None:
    """{"cci": float 0-100, "classification": str, "fng_value": int,
    "volume_z_score": float, "volume_direction": str} or None if either
    input signal is unavailable."""
    fng = get_crypto_fear_greed()
    vol = _volume_trend()
    if not fng or not vol:
        return None

    # Map volume z-score onto a 0-100 scale so it's comparable to fng_value,
    # then blend 60/40 sentiment/volume -- sentiment is the primary read,
    # volume confirms or discounts it.
    volume_score = max(0.0, min(100.0, 50 + vol["z_score"] * 20))
    cci = round(fng["value"] * 0.6 + volume_score * 0.4, 1)

    return {
        "cci": cci,
        "classification": _classify(cci),
        "fng_value": fng["value"],
        "volume_z_score": vol["z_score"],
        "volume_direction": vol["direction"],
    }


def get_crypto_conditions(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_crypto_conditions()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
