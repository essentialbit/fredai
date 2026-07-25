"""
FredAI Hypothesis Testing Loop (FSI L4)
===========================================
Fred currently reacts (chat) and predicts passively (backtesting_engine.py
grades the aggregate signal-implied direction after the fact). This module
is the first place Fred's own *stated* confidence gets checked against
reality over time: Fred proposes an explicit, falsifiable thesis on a
ticker with a live signal, the thesis is tracked forward, and resolution
feeds back into a confidence-calibration report (is Fred's stated 0.8
actually right ~80% of the time?), distinct from backtest's raw per-signal
accuracy.

Rate-limited and signal-gated: only tickers with a real sentiment signal or
technical reading get a thesis, and at most MAX_PER_DAY new hypotheses are
proposed per day, to avoid fabricating theses on quiet tickers (MISSION.md
Principle #7) or spending an LLM call per candidate ticker unbounded.
"""
import json
import re

from market_data import fetch_quotes
from memory_store import (
    insert_hypothesis, get_open_hypothesis_tickers, get_due_hypotheses,
    resolve_hypothesis, get_hypotheses, get_hypothesis_calibration,
    count_hypotheses_since, get_sentiment_snapshot,
)
from technical_alerts import get_technicals
from datetime import datetime, timedelta

MAX_PER_DAY = 3
MIN_SIGNAL_COUNT = 5
_VALID_DIRECTIONS = ("up", "down", "outperform_spy")

_HYPOTHESIS_PROMPT = """You are Fred, a financial intelligence system. You are looking at {ticker}, \
which has an active signal right now. State ONE falsifiable, specific investment thesis if -- and only \
if -- you genuinely have a reasoned view. Do not fabricate a thesis on thin evidence.

Context:
{context}

Respond with ONLY a JSON object, no markdown fences:
{{"has_thesis": true|false, "thesis": "1-2 sentence falsifiable claim", "direction": "up"|"down"|"outperform_spy", \
"confidence": 0.0-1.0, "horizon_days": 1-30}}

If the evidence is too thin or mixed for a genuine view, return {{"has_thesis": false}}."""


def _parse_hypothesis(text: str) -> dict | None:
    try:
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        data = json.loads(text)
        if not data.get("has_thesis"):
            return None
        if data.get("direction") not in _VALID_DIRECTIONS:
            return None
        confidence = float(data.get("confidence", 0))
        horizon = int(data.get("horizon_days", 0))
        if not (0.0 <= confidence <= 1.0) or not (1 <= horizon <= 30):
            return None
        if not data.get("thesis"):
            return None
        return data
    except Exception:
        return None


def _build_context(ticker: str, quote: dict, technicals: dict, sentiment: dict) -> str:
    lines = [f"Price: ${quote.get('price', 0):.2f} ({quote.get('change_pct', 0):+.2f}% today)"]
    if technicals.get("sma20") is not None and technicals.get("sma50") is not None:
        lines.append(f"SMA20: {technicals['sma20']:.2f} | SMA50: {technicals['sma50']:.2f}")
    if technicals.get("rsi14") is not None:
        lines.append(f"RSI14: {technicals['rsi14']:.1f}")
    if sentiment:
        lines.append(
            f"Sentiment: {sentiment.get('signal_type', 'neutral')} "
            f"(avg {sentiment.get('avg_sentiment', 0):.2f} over {sentiment.get('signal_count', 0)} signals)"
        )
    return "\n".join(lines)


def propose_hypothesis(ticker: str) -> int | None:
    """One bounded LLM call for this ticker. Returns the new hypothesis id,
    or None if there wasn't a real signal or Fred declined to state a thesis."""
    quotes = fetch_quotes([ticker, "SPY"])
    quote = quotes.get(ticker)
    if not quote or not quote.get("price"):
        return None

    technicals = get_technicals(ticker) or {}
    sentiment = get_sentiment_snapshot([ticker]).get(ticker, {})

    has_signal = (sentiment.get("signal_count", 0) >= MIN_SIGNAL_COUNT) or (
        technicals.get("sma20") is not None and technicals.get("sma50") is not None
    )
    if not has_signal:
        return None

    from agent import _provider, FRED_SYSTEM

    context = _build_context(ticker, quote, technicals, sentiment)
    prompt = _HYPOTHESIS_PROMPT.format(ticker=ticker, context=context)
    raw = _provider.complete(
        [{"role": "user", "content": prompt}], FRED_SYSTEM, tier="summary", max_tokens=400,
    )
    parsed = _parse_hypothesis(raw)
    if not parsed:
        return None

    spy_price = (quotes.get("SPY") or {}).get("price")
    return insert_hypothesis(
        ticker=ticker,
        thesis=parsed["thesis"],
        direction=parsed["direction"],
        confidence=parsed["confidence"],
        horizon_days=parsed["horizon_days"],
        price_at_creation=quote["price"],
        benchmark_at_creation=spy_price,
    )


def run_hypothesis_generation(candidate_tickers: list[str]) -> dict:
    """Scheduled job: propose up to MAX_PER_DAY new hypotheses among
    candidate tickers that don't already have one open."""
    since = datetime.utcnow() - timedelta(hours=24)
    already_today = count_hypotheses_since(since)
    budget = MAX_PER_DAY - already_today
    if budget <= 0:
        return {"proposed": 0, "skipped_budget": True}

    open_tickers = get_open_hypothesis_tickers()
    proposed = 0
    errors = 0
    for ticker in candidate_tickers:
        if proposed >= budget:
            break
        if ticker in open_tickers:
            continue
        try:
            hid = propose_hypothesis(ticker)
            if hid:
                proposed += 1
        except Exception as e:
            errors += 1
            print(f"[Hypothesis] {ticker} error: {e}")
    return {"proposed": proposed, "errors": errors, "budget": budget}


def _direction_correct(direction: str, actual_return: float | None, benchmark_return: float | None) -> bool | None:
    if actual_return is None:
        return None
    if direction == "up":
        return actual_return > 0
    if direction == "down":
        return actual_return < 0
    if direction == "outperform_spy":
        if benchmark_return is None:
            return None
        return actual_return > benchmark_return
    return None


def run_hypothesis_resolution() -> dict:
    """Scheduled job: for any hypothesis past resolves_at, fetch the actual
    price/benchmark return and grade it against the stated direction."""
    due = get_due_hypotheses()
    if not due:
        return {"resolved": 0, "errors": 0}

    tickers = list({h["ticker"] for h in due} | {"SPY"})
    quotes = fetch_quotes(tickers)
    resolved = 0
    errors = 0
    for h in due:
        price_now = (quotes.get(h["ticker"]) or {}).get("price")
        spy_now = (quotes.get("SPY") or {}).get("price")
        if price_now is None or not h.get("price_at_creation"):
            errors += 1
            continue

        actual_return = (price_now - h["price_at_creation"]) / h["price_at_creation"]
        benchmark_return = None
        if h.get("benchmark_at_creation") and spy_now is not None:
            benchmark_return = (spy_now - h["benchmark_at_creation"]) / h["benchmark_at_creation"]

        correct = _direction_correct(h["direction"], actual_return, benchmark_return)
        if correct is None:
            errors += 1
            continue

        resolve_hypothesis(
            h["id"], price_at_resolution=price_now, benchmark_at_resolution=spy_now,
            outcome="correct" if correct else "incorrect",
            actual_return=actual_return, benchmark_return=benchmark_return,
        )
        resolved += 1
    return {"resolved": resolved, "errors": errors}


def get_hypotheses_report() -> dict:
    return {
        "open": get_hypotheses(status="open", limit=50),
        "resolved": get_hypotheses(status="resolved", limit=50),
        "calibration": get_hypothesis_calibration(),
    }
