from datetime import datetime, timedelta
from memory_store import get_signals, get_sentiment_timeline, insert_trend, insert_alert


def compute_sentiment_stats(signals: list[dict]) -> dict:
    if not signals:
        return {"avg": 0.0, "bullish_pct": 0.0, "bearish_pct": 0.0, "count": 0}
    scores = [s["sentiment_score"] for s in signals if s.get("sentiment_score") is not None]
    types = [s["signal_type"] for s in signals if s.get("signal_type")]
    total = len(types)
    bullish = types.count("bullish")
    bearish = types.count("bearish")
    return {
        "avg": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "bullish_pct": round(bullish / total * 100, 1) if total else 0.0,
        "bearish_pct": round(bearish / total * 100, 1) if total else 0.0,
        "count": total,
    }


def detect_trends(quotes: dict) -> list[dict]:
    """Compare short (1h) vs long (4h) sentiment windows and detect shifts."""
    alerts = []
    now = datetime.utcnow()

    signals_1h = get_signals(hours=1)
    signals_4h = get_signals(hours=4)

    stats_1h = compute_sentiment_stats(signals_1h)
    stats_4h = compute_sentiment_stats(signals_4h)

    # Store aggregate trend
    insert_trend("MARKET", "sentiment_1h", stats_1h["avg"], _direction(stats_1h["avg"]))
    insert_trend("MARKET", "sentiment_4h", stats_4h["avg"], _direction(stats_4h["avg"]))
    insert_trend("MARKET", "bullish_pct", stats_1h["bullish_pct"], "")
    insert_trend("MARKET", "signal_volume", stats_1h["count"], "")

    # Sentiment shift detection
    delta = stats_1h["avg"] - stats_4h["avg"]
    if abs(delta) > 0.15:
        direction = "bullish surge" if delta > 0 else "bearish shift"
        msg = f"Market sentiment {direction}: 1h avg {stats_1h['avg']:+.2f} vs 4h avg {stats_4h['avg']:+.2f} (Δ {delta:+.2f})"
        alerts.append({"level": "warning" if delta < 0 else "info", "title": f"Sentiment Shift Detected", "message": msg, "asset": "MARKET"})
        insert_alert("warning" if delta < 0 else "info", "Sentiment Shift Detected", msg)

    # Volume spike detection
    if stats_4h["count"] > 0:
        expected_1h_vol = stats_4h["count"] / 4
        if stats_1h["count"] > expected_1h_vol * 2.5 and stats_1h["count"] > 10:
            msg = f"Signal volume spike: {stats_1h['count']} signals in 1h vs expected ~{expected_1h_vol:.0f}"
            alerts.append({"level": "warning", "title": "Volume Spike", "message": msg, "asset": "MARKET"})
            insert_alert("warning", "Volume Spike", msg)

    # Per-asset sentiment
    from config import WATCHLIST
    for asset in WATCHLIST:
        asset_signals_1h = [s for s in signals_1h if s.get("asset") == asset]
        asset_signals_4h = [s for s in signals_4h if s.get("asset") == asset]
        if len(asset_signals_4h) < 3:
            continue
        a1 = compute_sentiment_stats(asset_signals_1h)
        a4 = compute_sentiment_stats(asset_signals_4h)
        insert_trend(asset, "sentiment", a1["avg"], _direction(a1["avg"]))
        adelta = a1["avg"] - a4["avg"]
        if abs(adelta) > 0.2 and len(asset_signals_1h) >= 3:
            direction = "bullish" if adelta > 0 else "bearish"
            sym = asset.replace("-USD", "")
            msg = f"${sym} sentiment turning {direction}: {a1['bullish_pct']:.0f}% bullish in last hour"
            alerts.append({"level": "info" if adelta > 0 else "warning", "title": f"${sym} Signal Shift", "message": msg, "asset": asset})
            insert_alert("info" if adelta > 0 else "warning", f"${sym} Signal Shift", msg)

    # Price momentum alerts from quotes
    for sym, q in quotes.items():
        pct = q.get("change_pct", 0)
        if abs(pct) > 3:
            direction = "surging" if pct > 0 else "dropping"
            msg = f"{q['name']} is {direction} {pct:+.2f}% today"
            alerts.append({"level": "warning" if pct < 0 else "info", "title": f"Price Move: {sym}", "message": msg, "asset": sym})

    return alerts


def get_risk_level(stats: dict, alerts: list[dict]) -> str:
    bearish = stats.get("bearish_pct", 0)
    warning_count = sum(1 for a in alerts if a.get("level") == "warning")
    if bearish > 60 or warning_count >= 3:
        return "HIGH"
    elif bearish > 40 or warning_count >= 1:
        return "MEDIUM"
    return "LOW"


def _direction(score: float) -> str:
    if score > 0.05:
        return "up"
    elif score < -0.05:
        return "down"
    return "neutral"
