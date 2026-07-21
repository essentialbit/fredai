"""Bull/Bear adversarial debate over a single asset's thesis (MISSION.md L4,
Next Implementation Steps #1). Pure synthesis over signals FredAI already
computes -- no new external data source. Two Claude personas argue opposite
cases grounded in the same retrieved data, then a neutral Arbiter produces a
short, non-advice verdict. Cached per ticker/day since the underlying signals
move slowly (sentiment/insider/technicals/backtest accuracy)."""

import json
from datetime import datetime, timezone

from memory_store import (
    get_sentiment_snapshot,
    get_recent_insider_transactions,
    get_backtest_accuracy,
    get_short_interest_direction,
    get_market_debate,
    save_market_debate,
)
from technical_alerts import get_technicals

_ANTI_HALLUCINATION = (
    "Every claim you make MUST be grounded in the SIGNAL DATA block below -- never invent a "
    "price, rating, or figure that isn't there. If a data point is missing, say so explicitly "
    "(e.g. 'no insider activity on file') instead of filling the gap. This is not financial "
    "advice -- argue the case, don't issue a buy/sell directive."
)


def gather_signals(ticker: str) -> dict:
    """Pull every already-computed, already-stored signal FredAI has for
    this ticker. Read-only -- triggers no new API calls or fetches."""
    sentiment = get_sentiment_snapshot([ticker]).get(ticker)
    insider = get_recent_insider_transactions(ticker, days=90)
    technicals = get_technicals(ticker) or {}
    short_dir = get_short_interest_direction(ticker)
    backtest = get_backtest_accuracy(checkpoint="24h")

    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "insider_transactions": insider[:10],
        "technicals": technicals,
        "short_interest_direction": short_dir,
        "backtest_accuracy": {
            "accuracy_pct": backtest.get("accuracy_pct"),
            "baseline_delta_pct": backtest.get("baseline_delta_pct"),
            "total": backtest.get("total"),
        },
    }


def _format_signals(signals: dict) -> str:
    lines = [f"Ticker: {signals['ticker']}"]

    s = signals.get("sentiment")
    if s:
        lines.append(
            f"Sentiment: {s['signal_type']} (avg score {s['avg_sentiment']}, "
            f"{s['signal_count']} signals)"
        )
    else:
        lines.append("Sentiment: no signal coverage on file")

    tech = signals.get("technicals") or {}
    if tech:
        lines.append(
            f"Technicals: price ${tech.get('current')}, SMA20 {tech.get('sma20')}, "
            f"SMA50 {tech.get('sma50')}, RSI14 {tech.get('rsi14')}, "
            f"volume ratio vs 20d avg {tech.get('volume_ratio')}x"
        )
    else:
        lines.append("Technicals: no price history on file")

    insiders = signals.get("insider_transactions") or []
    if insiders:
        lines.append(f"Insider transactions (last 90d, {len(insiders)} shown):")
        for t in insiders[:5]:
            lines.append(
                f"  - {t.get('transaction_date')} {t.get('owner_name')} "
                f"({t.get('owner_title')}): {t.get('signal_type') or t.get('transaction_code')}"
            )
    else:
        lines.append("Insider transactions: none on file in the last 90 days")

    short_dir = signals.get("short_interest_direction")
    lines.append(f"Short interest trend: {short_dir or 'insufficient history to determine a trend'}")

    bt = signals.get("backtest_accuracy") or {}
    if bt.get("accuracy_pct") is not None:
        lines.append(
            f"Fred's aggregate 24h signal accuracy (all assets, not ticker-specific): "
            f"{bt['accuracy_pct']}% (n={bt['total']}, "
            f"{bt['baseline_delta_pct']:+.1f}pt vs. naive momentum baseline)"
            if bt.get("baseline_delta_pct") is not None else
            f"Fred's aggregate 24h signal accuracy (all assets, not ticker-specific): {bt['accuracy_pct']}% (n={bt['total']})"
        )

    return "\n".join(lines)


def bull_case(ticker: str, signals: dict) -> str:
    from agent import _provider

    system = (
        f"You are Fred's Bull persona -- you argue the strongest honest case FOR {ticker} "
        f"using only the data given. {_ANTI_HALLUCINATION}"
    )
    prompt = (
        f"SIGNAL DATA:\n{_format_signals(signals)}\n\n"
        f"Write the strongest bull case for {ticker} in 3-4 sentences, citing specific numbers "
        f"from the data above. If the data is genuinely thin, say so and keep the case short."
    )
    return _provider.complete(
        [{"role": "user", "content": prompt}], system, tier="rnd", max_tokens=400,
    )


def bear_case(ticker: str, signals: dict) -> str:
    from agent import _provider

    system = (
        f"You are Fred's Bear persona -- you argue the strongest honest case AGAINST {ticker} "
        f"using only the data given. {_ANTI_HALLUCINATION}"
    )
    prompt = (
        f"SIGNAL DATA:\n{_format_signals(signals)}\n\n"
        f"Write the strongest bear case for {ticker} in 3-4 sentences, citing specific numbers "
        f"from the data above. If the data is genuinely thin, say so and keep the case short."
    )
    return _provider.complete(
        [{"role": "user", "content": prompt}], system, tier="rnd", max_tokens=400,
    )


def arbiter_verdict(ticker: str, bull: str, bear: str, signals: dict) -> dict:
    from agent import _provider

    system = (
        "You are Fred's neutral Arbiter. You do not take a side and you never issue a buy/sell "
        "directive -- you weigh the Bull and Bear cases against the underlying data and produce a "
        "short, balanced synthesis. " + _ANTI_HALLUCINATION +
        ' Return ONLY valid JSON: {"verdict": "2-3 sentence balanced synthesis", '
        '"confidence": 0.0-1.0}. "confidence" reflects how much signal (not conviction of direction) '
        "the underlying data actually supports -- low confidence when data is thin, not when the "
        "cases disagree."
    )
    prompt = (
        f"SIGNAL DATA:\n{_format_signals(signals)}\n\n"
        f"BULL CASE:\n{bull}\n\nBEAR CASE:\n{bear}\n\n"
        f"Synthesize a balanced verdict for {ticker}."
    )
    raw = _provider.complete(
        [{"role": "user", "content": prompt}], system, tier="rnd", max_tokens=400,
    )
    try:
        import re
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw)
        match = re.search(r"\{[\s\S]*\}", clean)
        parsed = json.loads(match.group() if match else clean.strip())
        return {
            "verdict": parsed.get("verdict", raw.strip()),
            "confidence": float(parsed.get("confidence", 0.5)),
        }
    except Exception:
        return {"verdict": raw.strip(), "confidence": 0.5}


def get_market_debate_for(ticker: str, force_refresh: bool = False) -> dict:
    """Cached per ticker/day -- these signals move slowly, no need to re-run
    three LLM calls on every request."""
    ticker = ticker.upper()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not force_refresh:
        cached = get_market_debate(ticker, today)
        if cached:
            return {
                "ticker": ticker,
                "date": cached["debate_date"],
                "bull_case": cached["bull_case"],
                "bear_case": cached["bear_case"],
                "verdict": cached["verdict"],
                "confidence": cached["confidence"],
                "cached": True,
            }

    signals = gather_signals(ticker)
    bull = bull_case(ticker, signals)
    bear = bear_case(ticker, signals)
    arbiter = arbiter_verdict(ticker, bull, bear, signals)

    save_market_debate(
        ticker, today, bull, bear, arbiter["verdict"], arbiter["confidence"],
        json.dumps(signals, default=str),
    )

    return {
        "ticker": ticker,
        "date": today,
        "bull_case": bull,
        "bear_case": bear,
        "verdict": arbiter["verdict"],
        "confidence": arbiter["confidence"],
        "cached": False,
    }
