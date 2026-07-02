"""CNN Business Fear & Greed Index — high-level market sentiment context.

Unofficial CNN endpoint (no key required), commonly used in the finance
community. Requires a browser-like User-Agent + Referer or it 418s
("I'm a teapot. You're a bot.") — verified against the live endpoint.

Docs: none official; endpoint behavior confirmed empirically.
"""
import requests
from datetime import datetime

FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Accept": "application/json",
}

_cache: dict | None = None
_cache_expiry: float = 0
CACHE_TTL_SECONDS = 3600  # 1h — the index itself only updates a few times a day


def fetch_fear_greed() -> dict | None:
    """Returns {"score": float 0-100, "rating": str, "previous_close": float,
    "previous_1_week": float, "previous_1_month": float, "previous_1_year": float}
    or None on failure. Cached for CACHE_TTL_SECONDS."""
    global _cache, _cache_expiry
    now = datetime.utcnow().timestamp()
    if _cache and _cache_expiry > now:
        return _cache

    try:
        r = requests.get(FEAR_GREED_URL, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            print(f"[FearGreed] HTTP {r.status_code}")
            return _cache  # serve stale cache rather than nothing, if we have one
        data = r.json().get("fear_and_greed", {})
        if "score" not in data:
            return _cache
        _cache = data
        _cache_expiry = now + CACHE_TTL_SECONDS
        return _cache
    except Exception as e:
        print(f"[FearGreed] fetch error: {e}")
        return _cache
