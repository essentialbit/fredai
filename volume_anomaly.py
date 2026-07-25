"""Per-ticker signal+news volume anomaly detection (rolling z-score, L3).

Gap this closes: trend_detector.py's existing volume-spike check compares
total 1h signal count across the WHOLE market against a single static
constant -- it can't tell you a specific ticker is spiking. This computes
a per-ticker z-score of today's signal+news mention count against that
ticker's own rolling 30-day daily history, so a real per-asset spike is
visible even when the market overall looks quiet.

Zero new dependency -- pure stdlib statistics over news_items/signals,
both already ingested every cycle. Requires >=10 days of daily history
before flagging anything (same floor pattern used elsewhere in the app to
avoid false positives on thin data); until then this reports
"insufficient_history" rather than fabricate a reading from a handful of
days, same status shape /api/portfolio/risk already uses for the same
reason.
"""
import statistics
import time
from datetime import date, timedelta

from memory_store import get_conn, insert_alert, insert_volume_anomaly

_WINDOW_DAYS = 30
_MIN_HISTORY_DAYS = 10
_ELEVATED_Z = 2.5
_ANOMALOUS_Z = 4.0
_CACHE_TTL_S = 900  # 15 min, matching sector_rotation.py/credit_spread.py's TTL
_cache: dict = {}


def _daily_counts(ticker: str, window_days: int) -> dict[str, int]:
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    with get_conn() as conn:
        news_rows = conn.execute(
            "SELECT DATE(published_at) d, COUNT(*) c FROM news_items "
            "WHERE tickers = ? AND DATE(published_at) >= ? GROUP BY d",
            (ticker, cutoff),
        ).fetchall()
        signal_rows = conn.execute(
            "SELECT DATE(timestamp) d, COUNT(*) c FROM signals "
            "WHERE asset = ? AND DATE(timestamp) >= ? GROUP BY d",
            (ticker, cutoff),
        ).fetchall()
    counts: dict[str, int] = {}
    for r in news_rows:
        counts[r["d"]] = counts.get(r["d"], 0) + r["c"]
    for r in signal_rows:
        counts[r["d"]] = counts.get(r["d"], 0) + r["c"]
    return counts


def compute_volume_anomaly(ticker: str) -> dict:
    """{"status": "ok", "ticker", "count", "z_score", "level"} where level
    is "normal"/"elevated"/"anomalous", or {"status": "insufficient_history",
    "days", "min_days"} if the ticker doesn't have enough daily history yet."""
    counts = _daily_counts(ticker, _WINDOW_DAYS)
    today = date.today().isoformat()
    today_count = counts.pop(today, 0)
    baseline = list(counts.values())
    if len(baseline) < _MIN_HISTORY_DAYS:
        return {"status": "insufficient_history", "days": len(baseline), "min_days": _MIN_HISTORY_DAYS}

    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (today_count - mean) / stdev if stdev else 0.0

    if z >= _ANOMALOUS_Z:
        level = "anomalous"
    elif z >= _ELEVATED_Z:
        level = "elevated"
    else:
        level = "normal"

    if level != "normal":
        _record_and_alert(ticker, today, today_count, z, level)

    return {"status": "ok", "ticker": ticker, "count": today_count, "z_score": round(z, 2), "level": level}


def get_volume_anomaly_cached(ticker: str, force: bool = False) -> dict:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S per ticker."""
    now = time.time()
    entry = _cache.get(ticker)
    if not force and entry and now - entry["computed_at"] < _CACHE_TTL_S:
        return entry["data"]
    data = compute_volume_anomaly(ticker)
    _cache[ticker] = {"computed_at": now, "data": data}
    return data


def _record_and_alert(ticker: str, day: str, count: int, z: float, level: str) -> None:
    is_new = insert_volume_anomaly(ticker, day, count, round(z, 2), level)
    if not is_new:
        return  # already recorded/alerted today -- one alert per ticker per day
    insert_alert(
        "critical" if level == "anomalous" else "warning",
        f"${ticker} signal/news volume {level}",
        f"${ticker} saw {count} signal+news mentions today (z-score {z:.1f} vs its 30-day baseline).",
        ticker,
    )
