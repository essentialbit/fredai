"""Crypto Fear & Greed Index (alternative.me) -- crypto-specific sentiment
composite (volatility, momentum/volume, social media, dominance, search
trends). Distinct from the Bitcoin on-chain network-health metrics (pure
network fundamentals, not sentiment) and the existing CNN Fear & Greed badge
(an equity-market composite) -- a genuinely different signal type from both.

No signup/key required: https://api.alternative.me/fng/
"""
import time

import requests

from copper_gold_ratio import _trend

CRYPTO_FNG_URL = "https://api.alternative.me/fng/"
_CACHE_TTL_S = 3600  # 1h -- the index only updates once/day
_cache: dict = {"computed_at": 0.0, "data": None}


def compute_crypto_fear_greed() -> dict | None:
    """{"value": int 0-100, "classification": str, "trend_20d": {...}} or
    None if the endpoint can't be reached or returns too little history."""
    try:
        r = requests.get(CRYPTO_FNG_URL, params={"limit": 30, "format": "json"}, timeout=10)
        if r.status_code != 200:
            return None
        entries = r.json().get("data", [])
    except Exception as e:
        print(f"[CryptoFearGreed] fetch error: {e}")
        return None
    if not entries:
        return None

    # API returns newest-first; _trend() expects oldest-first (latest = series[-1])
    series = [float(e["value"]) for e in reversed(entries) if "value" in e]
    if len(series) < 8:
        return None

    trend_20d = _trend(series)
    if trend_20d is None:
        return None

    return {
        "value": int(series[-1]),
        "classification": entries[0].get("value_classification", ""),
        "trend_20d": trend_20d,
    }


def get_crypto_fear_greed(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_crypto_fear_greed()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
