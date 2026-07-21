"""Job-listing hiring-velocity signal (FSI L5, issue #228) -- open-role
count trend for a small curated set of public companies via Greenhouse's
public job board API (no signup, boards-api.greenhouse.io), read as a
hiring-momentum growth proxy: a sustained rise in open roles reads
expansion/confidence, a sustained drop reads cost-cutting/caution.

Greenhouse only exposes the current live listing count, not history, so
(same as geopolitical_risk.py) one row/day is persisted into its own table
and copper_gold_ratio.py's _trend() z-score shape is applied to that
persisted series once enough days have accumulated -- a live in-memory-only
cache could never build a real trailing window since there's no external
history to fall back on.

Each ticker->board-slug mapping is manually verified (Greenhouse 404s
silently on a wrong slug, no fuzzy match) -- same "unambiguous, individually
confirmed" discipline as oss_velocity_client.py's TRACKED_REPOS, and
deliberately avoiding the House-PTR ticker-ambiguity trap that killed #140.
"""
import time
from datetime import datetime, timezone

import requests

import memory_store
from copper_gold_ratio import _trend

TRACKED_BOARDS: dict[str, str] = {
    "COIN": "coinbase",
    "ABNB": "airbnb",
    "DDOG": "datadog",
    "HOOD": "robinhood",
}

_CACHE_TTL_S = 86400  # 24h, matches every other daily-cron macro/velocity badge
_cache: dict = {}  # ticker -> {"computed_at": float, "data": dict}

_TIMEOUT_S = 15


def fetch_open_role_count(slug: str) -> int | None:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        r = requests.get(url, timeout=_TIMEOUT_S)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    jobs = r.json().get("jobs")
    return len(jobs) if isinstance(jobs, list) else None


def _record_today(ticker: str, count: int) -> None:
    """Idempotent per (ticker, date) -- see memory_store's UNIQUE constraint."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    memory_store.record_job_listings_daily(ticker, today, count)


def compute_velocity_snapshot(ticker: str) -> dict | None:
    """{"ticker", "board_slug", "open_roles", "trend_20d"}, or None if the
    ticker isn't tracked or Greenhouse has no data for it right now."""
    ticker = ticker.upper()
    slug = TRACKED_BOARDS.get(ticker)
    if not slug:
        return None
    count = fetch_open_role_count(slug)
    if count is None:
        return None
    _record_today(ticker, count)

    history = memory_store.get_job_listings_history(ticker, days=90)
    if not history:
        return None
    series = [float(row["open_roles"]) for row in history]
    return {
        "ticker": ticker,
        "board_slug": slug,
        "open_roles": count,
        "trend_20d": _trend(series),
    }


def get_velocity_snapshot(ticker: str, force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S per ticker."""
    ticker = ticker.upper()
    if ticker not in TRACKED_BOARDS:
        return None
    now = time.time()
    entry = _cache.get(ticker)
    if not force and entry and now - entry["computed_at"] <= _CACHE_TTL_S:
        return entry["data"]

    data = compute_velocity_snapshot(ticker)
    if data is None:
        return entry["data"] if entry else None

    _cache[ticker] = {"computed_at": now, "data": data}
    return data
