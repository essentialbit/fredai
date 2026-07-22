"""Calendar seasonality — historical return bias by month-of-year and
day-of-week, computed straight from daily closes the app already knows how
to fetch (market_data.fetch_history). Deliberately a groupby-and-describe,
not a fitted model, so every number traces back to a visible sample size
(MISSION.md Principle #7) — same "show the math" style as portfolio_risk.py
and confluence_engine.py. This is unconditional historical base-rate,
distinct from #100's current-signal confluence and #9's prediction grading.
"""

import time
from collections import defaultdict
from datetime import datetime

from market_data import fetch_history

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

MIN_SAMPLE = 3  # below this, omit the period rather than print a low-confidence number

# Calendar seasonality doesn't move within a week by definition — cache
# aggressively so this is at most one multi-year history pull per symbol per week.
_HISTORY_TTL = 7 * 24 * 3600
_history_cache: dict[str, tuple[float, dict[str, float]]] = {}


def _multiyear_closes(symbol: str) -> dict[str, float]:
    """date (YYYY-MM-DD) -> close, as many years as Yahoo's chart API will serve."""
    now = time.time()
    hit = _history_cache.get(symbol)
    if hit and now - hit[0] < _HISTORY_TTL:
        return hit[1]
    # Degrade like portfolio_risk._daily_closes: longer ranges have their own
    # stricter Yahoo rate-limit budget that can exhaust before shorter ones do.
    for period in ("5y", "2y", "1y"):
        time.sleep(0.5)
        records = fetch_history(symbol, period=period, interval="1d")
        closes = {r["time"][:10]: r["close"] for r in records if r.get("close")}
        if closes:
            _history_cache[symbol] = (now, closes)
            return closes
    return {}


def _monthly_returns(closes: dict[str, float]) -> dict[int, list[float]]:
    """month (1-12) -> one whole-month return per year seen in the sample."""
    by_year_month: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
    for date_str, close in closes.items():
        year, month = date_str[:4], date_str[5:7]
        by_year_month[(int(year), int(month))][date_str] = close
    out: dict[int, list[float]] = defaultdict(list)
    for (_, month), day_closes in by_year_month.items():
        dates = sorted(day_closes)
        if len(dates) < 2:
            continue
        first, last = day_closes[dates[0]], day_closes[dates[-1]]
        if first > 0:
            out[month].append(last / first - 1.0)
    return out


def _daily_returns_by_dow(closes: dict[str, float]) -> dict[int, list[float]]:
    """weekday (0=Monday..6=Sunday) -> close-to-close daily returns landing on that weekday."""
    out: dict[int, list[float]] = defaultdict(list)
    prev_close = None
    for date_str in sorted(closes):
        close = closes[date_str]
        if prev_close is not None and prev_close > 0:
            dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()
            out[dow].append(close / prev_close - 1.0)
        prev_close = close
    return out


def _bias_stats(returns: list[float]) -> dict:
    n = len(returns)
    hits = sum(1 for r in returns if r > 0)
    return {
        "sample_size": n,
        "avg_return_pct": round(sum(returns) / n * 100, 2),
        "hit_rate_pct": round(hits / n * 100, 1),
    }


def compute_seasonal_bias(ticker: str) -> dict:
    """All 12 monthly biases + all 7 weekday biases for `ticker`. Periods with
    fewer than MIN_SAMPLE years/observations are simply omitted rather than
    padded with a fake number."""
    closes = _multiyear_closes(ticker)
    if len(closes) < 30:
        return {"ticker": ticker, "status": "insufficient_history"}

    monthly = _monthly_returns(closes)
    by_dow = _daily_returns_by_dow(closes)

    months = [
        {"period_value": m, "period_name": MONTH_NAMES[m - 1], **_bias_stats(monthly[m])}
        for m in range(1, 13) if len(monthly.get(m, [])) >= MIN_SAMPLE
    ]
    weekdays = [
        {"period_value": d, "period_name": DOW_NAMES[d], **_bias_stats(by_dow[d])}
        for d in range(7) if len(by_dow.get(d, [])) >= MIN_SAMPLE
    ]

    return {"ticker": ticker, "status": "ok", "months": months, "weekdays": weekdays}
