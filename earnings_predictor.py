"""Earnings surprise prediction (FSI L3): historical beat/miss base rate,
combined with the existing pre-earnings sentiment + insider-transaction
trend, into an interpretable, rules-based lean -- not a black-box model.

Ground truth (EPS estimate vs. reported) comes from yfinance's
Ticker.get_earnings_dates(), which is free, structured, and already a
project dependency's natural extension (Principle #2, no new source).
"""
import pandas as pd
import yfinance as yf

from memory_store import (
    get_earnings_beat_rate,
    get_recent_insider_transactions,
    get_sentiment_snapshot,
    insert_earnings_history,
)

PRE_EARNINGS_WINDOW_DAYS = 21


def fetch_earnings_history(ticker: str, limit: int = 12) -> list[dict]:
    """Wraps yfinance's Ticker(ticker).get_earnings_dates(limit=limit).
    Returns each quarter's eps_estimate/reported_eps/surprise_pct/earnings_date,
    oldest-complete-quarter first. The most recent row is often a future or
    just-happened unreported quarter with NaN actuals -- filtered out, never
    treated as a miss."""
    try:
        df = yf.Ticker(ticker.upper()).get_earnings_dates(limit=limit)
    except Exception as e:
        print(f"[Earnings] fetch error for {ticker}: {e}")
        return []
    if df is None or df.empty:
        return []

    rows = []
    for earnings_date, row in df.iterrows():
        reported = row.get("Reported EPS")
        if reported is None or pd.isna(reported):
            continue
        estimate = row.get("EPS Estimate")
        surprise = row.get("Surprise(%)")
        rows.append({
            "ticker": ticker.upper(),
            "earnings_date": earnings_date.date().isoformat(),
            "eps_estimate": None if estimate is None or pd.isna(estimate) else float(estimate),
            "reported_eps": float(reported),
            "surprise_pct": None if surprise is None or pd.isna(surprise) else float(surprise),
        })
    # yfinance's own `limit` isn't always respected internally (can return more
    # rows than requested) -- cap here to the most recent `limit` complete
    # quarters, which `rows` is already sorted newest-first before reversing.
    rows = rows[:limit]
    rows.reverse()
    return rows


def refresh_earnings_history(ticker: str, limit: int = 12) -> int:
    """Fetch + store. Returns rows newly inserted (0 if already up to date)."""
    rows = fetch_earnings_history(ticker, limit=limit)
    return insert_earnings_history(rows)


def predict_next_earnings_lean(ticker: str) -> dict:
    """Combines the historical beat-rate base rate with the pre-earnings
    signal trend (sentiment + insider transactions) into a simple,
    explainable lean. Every input that moves the score is shown -- v1 is
    deliberately not a black-box ML model."""
    ticker = ticker.upper()
    base_rate = get_earnings_beat_rate(ticker)
    if not base_rate:
        return {
            "ticker": ticker,
            "available": False,
            "reason": "no earnings history stored for this ticker yet",
        }

    lean_score = base_rate["beat_rate_pct"]
    adjustments = []

    sentiment = get_sentiment_snapshot([ticker], hours=PRE_EARNINGS_WINDOW_DAYS * 24).get(ticker)
    if sentiment and sentiment["signal_count"] >= 5:
        if sentiment["signal_type"] == "bullish":
            lean_score += 5
            adjustments.append({
                "factor": "pre-earnings sentiment",
                "detail": f"bullish across {sentiment['signal_count']} signals "
                          f"(avg {sentiment['avg_sentiment']:+.2f})",
                "delta": +5,
            })
        elif sentiment["signal_type"] == "bearish":
            lean_score -= 5
            adjustments.append({
                "factor": "pre-earnings sentiment",
                "detail": f"bearish across {sentiment['signal_count']} signals "
                          f"(avg {sentiment['avg_sentiment']:+.2f})",
                "delta": -5,
            })

    insider_txns = get_recent_insider_transactions(ticker, days=PRE_EARNINGS_WINDOW_DAYS, signal_only=True)
    if insider_txns:
        buys = sum(1 for t in insider_txns if t["acquired_disposed"] == "A")
        sells = sum(1 for t in insider_txns if t["acquired_disposed"] == "D")
        if buys > sells:
            lean_score += 5
            adjustments.append({
                "factor": "insider transactions",
                "detail": f"net buying, {buys} buy(s) vs {sells} sell(s) in last {PRE_EARNINGS_WINDOW_DAYS}d",
                "delta": +5,
            })
        elif sells > buys:
            lean_score -= 5
            adjustments.append({
                "factor": "insider transactions",
                "detail": f"net selling, {sells} sell(s) vs {buys} buy(s) in last {PRE_EARNINGS_WINDOW_DAYS}d",
                "delta": -5,
            })

    lean_score = max(0.0, min(100.0, lean_score))
    lean_label = "leans beat" if lean_score >= 60 else "leans miss" if lean_score <= 40 else "uncertain"

    return {
        "ticker": ticker,
        "available": True,
        "base_rate": base_rate,
        "adjustments": adjustments,
        "lean_score": round(lean_score, 1),
        "lean_label": lean_label,
        "summary": (
            f"historically beats {base_rate['beats']}/{base_rate['quarters']} quarters "
            f"(avg surprise {base_rate['avg_surprise_pct']:+.1f}%)"
            if base_rate["avg_surprise_pct"] is not None else
            f"historically beats {base_rate['beats']}/{base_rate['quarters']} quarters"
        ) + (f", current pre-print signal trend is {lean_label}" if adjustments else ""),
    }
