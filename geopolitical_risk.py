"""Geopolitical Risk Score -- keyword-weighted conflict/sanctions severity
signal from FredAI's own already-scraped 'geopolitical' news category
(news_client.py: Global Wire/AP/Reuters, CNBC Politics, BBC Business,
Al Jazeera, NHK Asia). Caldara & Iacoviello GPR-index methodology adapted
to this app's own corpus: count+weight conflict-related keywords per
article, aggregate into one daily average score (project proposal #216).

Unlike every other macro-strip badge (which pulls a full historical series
live from an external API on every call), this app's own news_items table
only retains NEWS_RETENTION_HOURS (72h default, config.py) of raw articles
-- nowhere near the 90-day trailing baseline a z-score needs. So the daily
aggregate score is persisted into its own small table
(geopolitical_risk_daily, one row/day) instead of being recomputed from
article history that no longer exists by the time it would be needed, then
copper_gold_ratio.py's _trend() z-score shape is applied to that persisted
series once enough days have accumulated (same "starts empty, builds up
over time" bootstrap every other z-score badge already has -- the
difference here is *what* is bootstrapping: our own daily rollup, not the
source data itself).
"""
import re
import time
from datetime import datetime, timezone

import memory_store
from copper_gold_ratio import _trend

_CACHE_TTL_S = 900  # 15 min, matching every other macro-strip badge

_cache: dict = {"computed_at": 0.0, "data": None}

# Tiered severity weights -- sanity-checked against known historical spike
# terms, not a precise calibration (see proposal #216). Top tier covers
# active-conflict language, mid tier economic-warfare language, lower tier
# instability short of open conflict.
_WEIGHTS: dict[float, tuple[str, ...]] = {
    3.0: ("war", "invasion", "nuclear", "airstrike", "missile strike"),
    1.5: ("sanctions", "tariff", "trade war", "military buildup", "blockade"),
    0.75: ("unrest", "coup", "protest", "embargo", "conflict"),
}
_MAX_ARTICLE_SCORE = 6.0  # caps one alarmist headline from dominating the day

_BAND_CALM_MAX = 1.0
_BAND_ELEVATED_MAX = 2.5

# Word-boundary regex per keyword -- a naive substring `in` check would false-
# positive "war" against "toward"/"warning"/"warranty"/"software" etc., the
# same false-positive class already documented against risk_rules.py's plain
# substring matching (see project memory). \b works fine for multi-word
# phrases too since re.escape preserves the internal space.
_KEYWORD_PATTERNS: list[tuple[float, re.Pattern]] = [
    (weight, re.compile(r"\b" + re.escape(kw) + r"\b"))
    for weight, keywords in _WEIGHTS.items()
    for kw in keywords
]


def score_article(title: str, description: str = "") -> float:
    """Sum matched-keyword weights across all tiers, capped per article."""
    text = f"{title or ''} {description or ''}".lower()
    total = sum(weight for weight, pattern in _KEYWORD_PATTERNS if pattern.search(text))
    return min(total, _MAX_ARTICLE_SCORE)


def _band(score: float) -> str:
    if score < _BAND_CALM_MAX:
        return "calm"
    if score < _BAND_ELEVATED_MAX:
        return "elevated"
    return "severe"


def _record_today() -> None:
    """Idempotent per calendar day (UTC) -- see memory_store's UNIQUE(date)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    articles = memory_store.get_news(category="geopolitical", hours=24, limit=500)
    if not articles:
        return
    scores = [score_article(a.get("title"), a.get("description")) for a in articles]
    avg_score = sum(scores) / len(scores)
    memory_store.record_geopolitical_risk_daily(today, avg_score, len(articles))


def compute_geopolitical_risk() -> dict | None:
    """{"score": float, "band": "calm"/"elevated"/"severe", "article_count": int,
    "date": "YYYY-MM-DD", "trend_20d": {...} or None} -- trend_20d stays None
    until >=8 days of persisted history exist (same _trend() floor as every
    other macro badge), or None entirely if today has no geopolitical
    articles yet and no prior history exists either."""
    _record_today()
    history = memory_store.get_geopolitical_risk_history(days=90)
    if not history:
        return None
    latest = history[-1]
    series = [row["score"] for row in history]
    return {
        "score": round(latest["score"], 2),
        "band": _band(latest["score"]),
        "article_count": latest["article_count"],
        "date": latest["date"],
        "trend_20d": _trend(series),
    }


def get_geopolitical_risk(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_geopolitical_risk()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
