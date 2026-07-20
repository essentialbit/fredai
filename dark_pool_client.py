"""Weekly off-exchange (dark pool / Alternative Trading System) share-volume
signal (FSI L2, issue #239) -- distinct from the already-shipped FINRA Reg
SHO short-volume ratio (issue #184), which tracks lit-exchange short-sale
flagging on a daily basis. This tracks total off-exchange execution volume
per symbol per week, a well-known institutional positioning gauge.

Source: FINRA's public OTC Transparency "weeklySummary" API
(api.finra.org/data/group/otcMarket/name/weeklySummary), POST + JSON body,
no signup or API key required -- same read-only public market-data trust
boundary as every other FINRA/SEC/FRED integration in this codebase.

IMPORTANT publication lag: FINRA publishes this data on a ~2-3 week delay
(confirmed live -- the most recent available weekStartDate is routinely
2-3 calendar weeks behind "today"). Never present this as a same-week or
real-time signal; the trend/direction below is meaningful, the "latest"
week label is not current.
"""
import statistics
import time
from datetime import date, timedelta

import requests

_URL = "https://api.finra.org/data/group/otcMarket/name/weeklySummary"
_LOOKBACK_DAYS = 150  # comfortably covers ~13+ published weeks despite the 2-3wk lag
_TIMEOUT_S = 20
_CACHE_TTL_S = 86400  # 24h, matches every other macro/velocity badge's cache

_cache: dict = {}  # ticker -> {"computed_at": float, "data": dict}


def fetch_weekly_volume(ticker: str) -> list[tuple[str, float]] | None:
    """[(weekStartDate, total_off_exchange_shares), ...] oldest-first, summed
    across every reporting ATS venue for that symbol+week. None on a bad
    ticker (FINRA returns 204/empty) or a request failure."""
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    body = {
        "compareFilters": [
            {"compareType": "EQUAL", "fieldName": "issueSymbolIdentifier", "fieldValue": ticker.upper()},
            {"compareType": "EQUAL", "fieldName": "summaryTypeCode", "fieldValue": "ATS_W_SMBL_FIRM"},
        ],
        "dateRangeFilters": [
            {"startDate": start.isoformat(), "endDate": end.isoformat(), "fieldName": "weekStartDate"}
        ],
        "limit": 5000,
    }
    try:
        resp = requests.post(
            _URL, json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.content:
        return None
    try:
        rows = resp.json()
    except ValueError:
        return None
    if not rows:
        return None

    by_week: dict = {}
    for row in rows:
        wk = row.get("weekStartDate")
        qty = row.get("totalWeeklyShareQuantity")
        if wk is None or qty is None:
            continue
        by_week[wk] = by_week.get(wk, 0.0) + float(qty)
    if not by_week:
        return None
    return sorted(by_week.items())


def _trend(series: list[float]) -> dict | None:
    """Same shape as copper_gold_ratio.py's _trend() -- rolling z-score/
    direction vs. the trailing window, excluding the latest point from its
    own baseline."""
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
    return {"latest": round(latest, 0), "mean": round(mean, 0), "z_score": round(z, 2), "direction": direction}


def compute_dark_pool_signal(ticker: str) -> dict | None:
    """{"ticker", "week_start_date", "off_exchange_shares", "trend",
    "weeks_available"}, or None if fewer than 8 published weeks exist for
    this symbol (too illiquid on ATS venues, or an invalid ticker)."""
    weekly = fetch_weekly_volume(ticker)
    if not weekly or len(weekly) < 8:
        return None
    trailing = weekly[-13:]  # spec's ~13 trailing weekly points
    trend = _trend([qty for _, qty in trailing])
    if trend is None:
        return None
    latest_week, latest_qty = trailing[-1]
    return {
        "ticker": ticker.upper(),
        "week_start_date": latest_week,
        "off_exchange_shares": round(latest_qty, 0),
        "trend": trend,
        "weeks_available": len(trailing),
    }


def get_dark_pool_signal(ticker: str, force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S per
    ticker, same lazy-per-symbol pattern as oss_velocity_client.py."""
    ticker = ticker.upper()
    now = time.time()
    entry = _cache.get(ticker)
    if not force and entry and now - entry["computed_at"] <= _CACHE_TTL_S:
        return entry["data"]

    data = compute_dark_pool_signal(ticker)
    if data is None:
        return entry["data"] if entry else None

    _cache[ticker] = {"computed_at": now, "data": data}
    return data
