"""
Signal Density Scorer — surfaces highest-intelligence stocks.

Score = weighted composite of:
  - news_volume     : news articles in last 24h (normalised)
  - assessment      : BUY/SELL conviction from Fred's assessment cache
  - price_momentum  : abs(change_pct) normalised
  - earnings_prox   : inverse distance to next earnings event
  - graph_activity  : number of cascade relationships (breadth of exposure)
"""
import time
from datetime import datetime

WEIGHTS = {
    "news_volume":    0.25,
    "assessment":     0.30,
    "price_momentum": 0.20,
    "earnings_prox":  0.15,
    "graph_activity": 0.10,
}

SIGNAL_SCORES = {"BUY": 1.0, "SELL": 0.85, "WATCH": 0.4, "HOLD": 0.2}
CONVICTION_MUL = {"HIGH": 1.3, "MEDIUM": 1.0, "LOW": 0.7}

_cache: dict = {"ts": 0, "scores": []}
_TTL = 600  # 10 min


def compute_signal_density(
    symbols: list[str],
    quotes: dict,
    get_news_fn,
    get_calendar_fn,
    assessment_cache: dict,
    adjacency: dict = None,
) -> list[dict]:
    """
    Returns ranked list (highest density first).

    assessment_cache: {symbol: {"ts":..., "data": assessment_dict}} as used by graph_engine
    adjacency: optional {symbol: [neighbors]} for graph_activity scoring
    """
    now = time.time()
    if (now - _cache["ts"]) < _TTL and _cache["scores"]:
        return _cache["scores"]

    # Pre-fetch calendar for earnings proximity
    try:
        calendar_events = get_calendar_fn(days=14)
    except Exception:
        calendar_events = []

    earnings_map: dict = {}
    for ev in calendar_events:
        sym = ev.get("symbol", "")
        if not sym or ev.get("event_type") != "earnings":
            continue
        try:
            ev_date = datetime.fromisoformat(ev["event_date"])
            days_out = (ev_date - datetime.utcnow()).days
            if 0 <= days_out:
                prev = earnings_map.get(sym, 999)
                earnings_map[sym] = min(prev, days_out)
        except Exception:
            pass

    scores = []
    for sym in symbols:
        q = quotes.get(sym, {})
        price_chg = abs(q.get("change_pct", 0))

        # News volume
        try:
            news = get_news_fn(ticker=sym, hours=24, limit=100)
            news_count = len(news)
        except Exception:
            news_count = 0
        news_score = min(1.0, news_count / 8.0)

        # Assessment signal
        raw_assess = assessment_cache.get(sym)
        assess_data = {}
        if isinstance(raw_assess, dict):
            assess_data = raw_assess.get("data", raw_assess)
        signal = assess_data.get("signal", "HOLD")
        conviction = assess_data.get("conviction", "MEDIUM")
        assess_score = min(1.0,
            SIGNAL_SCORES.get(signal, 0.2) * CONVICTION_MUL.get(conviction, 1.0)
        )

        # Price momentum
        momentum_score = min(1.0, price_chg / 8.0)

        # Earnings proximity (0 if >30d out)
        days_out = earnings_map.get(sym, 999)
        earn_score = max(0.0, 1.0 - days_out / 30.0) if days_out < 30 else 0.0

        # Graph activity (number of known relationships)
        graph_score = 0.0
        if adjacency:
            n_rels = len(adjacency.get(sym, []))
            graph_score = min(1.0, n_rels / 10.0)

        total = (
            WEIGHTS["news_volume"]    * news_score +
            WEIGHTS["assessment"]     * assess_score +
            WEIGHTS["price_momentum"] * momentum_score +
            WEIGHTS["earnings_prox"]  * earn_score +
            WEIGHTS["graph_activity"] * graph_score
        )

        scores.append({
            "symbol": sym,
            "score": round(total, 3),
            "score_pct": round(total * 100, 1),
            "signal": signal,
            "conviction": conviction,
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "news_count_24h": news_count,
            "days_to_earnings": days_out if days_out < 999 else None,
            "breakdown": {
                "news":      round(news_score, 2),
                "assess":    round(assess_score, 2),
                "momentum":  round(momentum_score, 2),
                "earnings":  round(earn_score, 2),
                "graph":     round(graph_score, 2),
            },
            "generated_at": datetime.utcnow().isoformat(),
        })

    scores.sort(key=lambda x: x["score"], reverse=True)
    _cache["ts"] = now
    _cache["scores"] = scores
    return scores


def invalidate():
    _cache["ts"] = 0
