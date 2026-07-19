"""Sentiment reversal early warning (FSI L3) -- detects the *moment* a
sustained sentiment trend flips direction (bearish->bullish or vice versa),
using signals FredAI already collects continuously. Distinct from
confluence_engine.py (current-snapshot synthesis) and backtesting_engine.py
(after-the-fact price accuracy): this is trend-flip-in-progress detection.

Deliberately does not claim price will follow -- the signal trend flipped,
that's all (Principle #7: no fabricated conviction)."""

from datetime import datetime, timedelta

from memory_store import get_signals_with_fallback, insert_trend, insert_alert, get_trend_history

MIN_WINDOW_SIGNALS = 5
REVERSAL_MAGNITUDE_THRESHOLD = 0.15


def _parse_timestamp(raw: str | None) -> datetime | None:
    """Signals carry two coexisting timestamp separator formats (space from
    DEFAULT CURRENT_TIMESTAMP columns, 'T' from news_items' isoformat writes)
    -- normalize both rather than assume one."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def detect_sentiment_reversal(ticker: str, short_window_days: int = 3, long_window_days: int = 14,
                               min_window_signals: int = MIN_WINDOW_SIGNALS,
                               magnitude_threshold: float = REVERSAL_MAGNITUDE_THRESHOLD) -> dict | None:
    """Compare avg sentiment over a short recent window against the longer
    prior baseline window. Flags a reversal only when the sign flips AND
    both windows clear a minimum signal floor (avoid flagging noise from a
    couple of stray signals) AND the magnitude crosses a threshold."""
    combined = get_signals_with_fallback(hours=long_window_days * 24, asset=ticker, limit=2000, min_real=1)
    if not combined:
        return None

    short_cutoff = datetime.utcnow() - timedelta(days=short_window_days)
    short_scores: list[float] = []
    baseline_scores: list[float] = []
    for s in combined:
        ts = _parse_timestamp(s.get("timestamp"))
        if ts is None:
            continue
        score = s.get("sentiment_score") or 0.0
        (short_scores if ts >= short_cutoff else baseline_scores).append(score)

    if len(short_scores) < min_window_signals or len(baseline_scores) < min_window_signals:
        return None

    short_avg = sum(short_scores) / len(short_scores)
    baseline_avg = sum(baseline_scores) / len(baseline_scores)

    if short_avg == 0 or baseline_avg == 0 or (short_avg > 0) == (baseline_avg > 0):
        return None

    magnitude = abs(short_avg - baseline_avg)
    if magnitude < magnitude_threshold:
        return None

    return {
        "ticker": ticker,
        "direction": "bearish_to_bullish" if baseline_avg < 0 else "bullish_to_bearish",
        "short_window_avg": round(short_avg, 3),
        "baseline_window_avg": round(baseline_avg, 3),
        "magnitude": round(magnitude, 3),
        "short_window_count": len(short_scores),
        "baseline_window_count": len(baseline_scores),
        "short_window_days": short_window_days,
        "long_window_days": long_window_days,
    }


def check_reversals(tickers: list[str], short_window_days: int = 3, long_window_days: int = 14) -> list[dict]:
    """Batch entry point for the scan cycle: runs detect_sentiment_reversal
    per ticker, logs every hit to trends (so get_trend_history already
    surfaces it on symbol detail views), and fires one alert per direction
    per short_window_days window (avoids re-alerting every scan cycle while
    a sustained flip condition persists)."""
    alerts = []
    for ticker in tickers:
        result = detect_sentiment_reversal(ticker, short_window_days=short_window_days, long_window_days=long_window_days)
        if not result:
            continue

        insert_trend(ticker, "sentiment_reversal", result["short_window_avg"], result["direction"])

        recent = get_trend_history(ticker, "sentiment_reversal", hours=short_window_days * 24)
        already_alerted = any(r["trend_direction"] == result["direction"] for r in recent[:-1])
        if already_alerted:
            continue

        readable = "bearish -> bullish" if result["direction"] == "bearish_to_bullish" else "bullish -> bearish"
        msg = (f"${ticker} sentiment trend flipped {readable}: "
               f"{result['long_window_days']}d baseline {result['baseline_window_avg']:+.2f} -> "
               f"{result['short_window_days']}d recent {result['short_window_avg']:+.2f} "
               f"(Δ{result['magnitude']:+.2f}, {result['short_window_count']} recent signals) "
               f"-- signal trend flipped direction, not a price prediction")
        level = "info" if result["direction"] == "bearish_to_bullish" else "warning"
        title = f"${ticker} Sentiment Reversal"
        alerts.append({"level": level, "title": title, "message": msg, "asset": ticker})
        insert_alert(level, title, msg, ticker)

    return alerts
