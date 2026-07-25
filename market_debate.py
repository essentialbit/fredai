"""Adversarial Research Desk: Bull/Bear/Risk Officer/PM committee over a
single asset's thesis (MISSION.md L4, FSI Build Playbook Feature 7).

Extends the original Bull/Bear/Arbiter debate (MISSION.md L4, Next
Implementation Steps #1) rather than standing up a parallel system --
this repo already independently shipped TWO separate ticker-debate
implementations (this module and ticker_debate.py) before this feature;
adding a third would have made that worse. This module is the one wired
into the main dashboard's "Bull/Bear Debate" toggle, so it's the one
extended.

Cost control is a first-class requirement, not an afterthought: Bull/
Bear/Risk use the cheap LLM tier (was "rnd"/Opus for all three roles
before this feature -- a real cost regression fixed here, not just a new
one avoided), the PM synthesis uses the chat tier only. A rough
chars/4 token estimate is tracked per run and capped at
config.COMMITTEE_MAX_TOKENS -- if the budget would be exceeded before the
Risk Officer or PM step, the run degrades to the original cheaper Bull/
Bear/simple-verdict shape rather than failing or silently overspending.

Every verdict is auto-logged as a trackable signal (source='committee')
via the same signal_outcomes pipeline every other source uses
(backtesting_engine.py/calibration_engine.py) -- the committee earns or
loses credibility exactly like any other source, not a special case.

Cached per ticker/day since the underlying signals move slowly
(sentiment/insider/technicals/backtest accuracy).
"""

import json
import re
from datetime import datetime, timezone

from config import COMMITTEE_MAX_TOKENS
from memory_store import (
    get_sentiment_snapshot,
    get_recent_insider_transactions,
    get_backtest_accuracy,
    get_short_interest_direction,
    get_market_debate,
    save_market_debate,
    insert_signal,
    log_signal_outcome,
)
from technical_alerts import get_technicals

_ANTI_HALLUCINATION = (
    "Every claim you make MUST be grounded in the SIGNAL DATA block below -- never invent a "
    "price, rating, or figure that isn't there. If a data point is missing, say so explicitly "
    "(e.g. 'no insider activity on file') instead of filling the gap. This is not financial "
    "advice -- argue the case, don't issue a buy/sell directive."
)

_CONTESTED_MARGIN = 0.15  # |bull_score - bear_score| below this = "contested", the most informative disagreement state


def _estimate_tokens(text: str) -> int:
    """Rough chars/4 heuristic, NOT an exact billed token count -- providers
    don't return usage from agent.py's complete() today. Good enough for a
    soft budget cap, not for billing reconciliation."""
    return max(1, len(text or "") // 4)


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


def _committee_track_record() -> str:
    """The committee's OWN historical accuracy, not agent_track_record
    (that table tracks Claude/Gemini self-improvement proposal outcomes --
    an unrelated system despite the similar name, same confusion class as
    debate.py). Degrades to an honest 'no track record yet' when sparse."""
    report = get_backtest_accuracy(checkpoint="24h").get("sources", {}).get("committee")
    if not report or report.get("total", 0) < 10:
        return "No established track record yet (fewer than 10 resolved committee verdicts)."
    return (f"{report['accuracy_pct']:.1f}% accuracy over {report['total']} resolved verdicts "
            f"({report.get('baseline_delta_pct', 0):+.1f}pt vs naive baseline)")


def bull_case(ticker: str, signals: dict) -> str:
    """Never raises -- a provider error returns an honest placeholder
    string instead of crashing the whole committee run. Every role here
    needs this (not just pm_verdict) for 'graceful degradation... when
    providers are constrained' to actually hold end-to-end (gap found
    alongside pm_verdict's own missing error handling, same class)."""
    try:
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
        return _provider.complete([{"role": "user", "content": prompt}], system, tier="summary", max_tokens=300)
    except Exception:
        return "Bull case unavailable this run (provider error)."


def bear_case(ticker: str, signals: dict) -> str:
    """Never raises -- see bull_case's docstring."""
    try:
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
        return _provider.complete([{"role": "user", "content": prompt}], system, tier="summary", max_tokens=300)
    except Exception:
        return "Bear case unavailable this run (provider error)."


def risk_officer_case(ticker: str, signals: dict, bull: str, bear: str) -> str:
    """What invalidates EACH case, and position-sizing concerns. Regime-fit
    commentary is intentionally omitted -- Regime Detection (a separate
    FSI Build Playbook feature) hasn't shipped, and fabricating a regime
    read here would violate the data-correctness standing rule. Never
    raises -- see bull_case's docstring."""
    try:
        from agent import _provider
        system = (
            f"You are Fred's Risk Officer persona for {ticker} -- you don't argue a direction, you "
            f"stress-test BOTH the bull and bear cases. {_ANTI_HALLUCINATION}"
        )
        prompt = (
            f"SIGNAL DATA:\n{_format_signals(signals)}\n\nBULL CASE:\n{bull}\n\nBEAR CASE:\n{bear}\n\n"
            f"In 3-4 sentences: what specific data point or event would INVALIDATE the bull case? "
            f"What would invalidate the bear case? Flag any position-sizing concern (e.g. thin data, "
            f"high volatility, conflicting signals) a risk-aware reader should know."
        )
        return _provider.complete([{"role": "user", "content": prompt}], system, tier="summary", max_tokens=300)
    except Exception:
        return "Risk Officer assessment unavailable this run (provider error)."


_PM_PROMPT = """SIGNAL DATA:
{signals}

BULL CASE:
{bull}

BEAR CASE:
{bear}

RISK OFFICER:
{risk}

COMMITTEE'S OWN HISTORICAL TRACK RECORD: {track_record}

Weigh all three cases plus the committee's own track record (a low/no track record means less
weight on conviction, not zero -- say so honestly) into one verdict for {ticker}.

Respond with ONLY a JSON object, no markdown fences:
{{"direction": "bullish"|"bearish"|"neutral", "conviction": 0-100, "time_horizon": "short-term (days)"|"medium-term (weeks)"|"long-term (months+)",
"key_risks": ["...", "...", "..."], "invalidation_trigger": "one sentence -- what specific event would flip this verdict",
"bull_score": 0.0-1.0, "bear_score": 0.0-1.0, "rationale": "2-3 sentence synthesis"}}

"bull_score"/"bear_score" independently rate how STRONG each case is on its own merits (not
relative to each other) -- two strong opposing cases is a real, valuable signal (a genuinely
contested situation), not something to average away."""


def pm_verdict(ticker: str, signals: dict, bull: str, bear: str, risk: str) -> dict | None:
    """Strict-JSON PM synthesis. None (never fabricated) on ANY failure --
    provider error/timeout as well as a parse failure -- caller falls back
    to the degraded verdict path. The provider call itself must be inside
    the try block, not just the parsing: a provider outage during this
    call is exactly the 'graceful degradation... when providers are
    constrained' case the HARD CONSTRAINT calls out, not a crash (caught
    in verification)."""
    from agent import _provider
    system = (
        "You are Fred's Portfolio Manager persona -- you synthesize the Bull, Bear, and Risk "
        "Officer briefs plus the committee's own track record into one accountable verdict. You "
        "never issue a buy/sell directive, only a calibrated read. " + _ANTI_HALLUCINATION
    )
    prompt = _PM_PROMPT.format(
        signals=_format_signals(signals), bull=bull, bear=bear, risk=risk,
        track_record=_committee_track_record(), ticker=ticker,
    )
    try:
        raw = _provider.complete([{"role": "user", "content": prompt}], system, tier="chat", max_tokens=500)
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw)
        match = re.search(r"\{[\s\S]*\}", clean)
        parsed = json.loads(match.group() if match else clean.strip())
        if parsed.get("direction") not in ("bullish", "bearish", "neutral"):
            return None
        conviction = int(parsed.get("conviction", 50))
        key_risks = parsed.get("key_risks")
        if not isinstance(key_risks, list):
            key_risks = []
        return {
            "direction": parsed["direction"],
            "conviction": max(0, min(100, conviction)),
            "time_horizon": str(parsed.get("time_horizon", "medium-term (weeks)")),
            "key_risks": key_risks[:3],
            "invalidation_trigger": str(parsed.get("invalidation_trigger", "")),
            "bull_score": max(0.0, min(1.0, float(parsed.get("bull_score", 0.5)))),
            "bear_score": max(0.0, min(1.0, float(parsed.get("bear_score", 0.5)))),
            "rationale": str(parsed.get("rationale", "")),
            "raw_tokens": _estimate_tokens(raw),
        }
    except Exception:
        return None


def _degraded_verdict(ticker: str, bull: str, bear: str, signals: dict) -> dict:
    """Cheap-tier fallback matching the original (pre-committee) Bull/Bear/
    simple-verdict shape -- used when the token budget would be exceeded
    before the Risk Officer/PM steps, or when pm_verdict() fails to parse.
    This IS the 'graceful degradation to the existing two-agent debate'
    HARD CONSTRAINT, not an error path -- and since it's the last-resort
    fallback, it must never itself raise (the provider call is inside the
    try, same fix as pm_verdict's own missing coverage)."""
    try:
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
        prompt = f"SIGNAL DATA:\n{_format_signals(signals)}\n\nBULL CASE:\n{bull}\n\nBEAR CASE:\n{bear}\n\nSynthesize a balanced verdict for {ticker}."
        raw = _provider.complete([{"role": "user", "content": prompt}], system, tier="summary", max_tokens=250)
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw)
        match = re.search(r"\{[\s\S]*\}", clean)
        parsed = json.loads(match.group() if match else clean.strip())
        return {"verdict": parsed.get("verdict", raw.strip()), "confidence": float(parsed.get("confidence", 0.5))}
    except Exception:
        return {"verdict": "Research Desk is temporarily unavailable (provider error) -- see the Bull/Bear cases above.", "confidence": 0.0}


def _log_committee_outcome(ticker: str, direction: str) -> None:
    """Trackable signal (source='committee') so backtesting_engine/
    calibration_engine score this exactly like any other source. Never
    raises -- a live quote fetch failure must not break verdict delivery,
    just skip track-record logging for this run."""
    try:
        from market_data import fetch_quotes
        from backtesting_engine import _baseline_direction
        quote = (fetch_quotes([ticker]) or {}).get(ticker)
        price = (quote or {}).get("price")
        baseline = _baseline_direction(quote)
        insert_signal(source="committee", asset=ticker, content=f"Research Desk verdict: {direction}",
                      signal_type=direction if direction in ("bullish", "bearish") else "neutral")
        if price is not None:
            log_signal_outcome(
                asset=ticker, predicted_direction=direction, signal_count=1, avg_sentiment=None,
                price_at_t0=price, source="committee", baseline_direction=baseline,
            )
    except Exception as e:
        print(f"[ResearchDesk] Track-record logging failed for {ticker}: {e}")


def get_market_debate_for(ticker: str, force_refresh: bool = False) -> dict:
    """Cached per ticker/day -- these signals move slowly, no need to re-run
    the committee on every request."""
    ticker = ticker.upper()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not force_refresh:
        cached = get_market_debate(ticker, today)
        if cached:
            return {
                "ticker": ticker, "date": cached["debate_date"],
                "bull_case": cached["bull_case"], "bear_case": cached["bear_case"],
                "risk_case": cached.get("risk_case"),
                "verdict": cached["verdict"], "confidence": cached["confidence"],
                "direction": cached.get("direction"), "conviction": cached.get("conviction"),
                "time_horizon": cached.get("time_horizon"),
                "key_risks": json.loads(cached["key_risks"]) if cached.get("key_risks") else [],
                "invalidation_trigger": cached.get("invalidation_trigger"),
                "bull_score": cached.get("bull_score"), "bear_score": cached.get("bear_score"),
                "contested": bool(cached.get("contested")),
                "est_tokens": cached.get("est_tokens"),
                "cached": True,
            }

    signals = gather_signals(ticker)
    bull = bull_case(ticker, signals)
    bear = bear_case(ticker, signals)
    est_tokens = _estimate_tokens(_format_signals(signals)) * 3 + _estimate_tokens(bull) + _estimate_tokens(bear)

    risk_case = None
    pm = None
    if est_tokens < COMMITTEE_MAX_TOKENS:
        risk_case = risk_officer_case(ticker, signals, bull, bear)
        est_tokens += _estimate_tokens(risk_case)
        if est_tokens < COMMITTEE_MAX_TOKENS:
            pm = pm_verdict(ticker, signals, bull, bear, risk_case)
            if pm:
                est_tokens += pm.pop("raw_tokens", 0)

    if pm:
        direction, conviction = pm["direction"], pm["conviction"]
        time_horizon, key_risks = pm["time_horizon"], pm["key_risks"]
        invalidation_trigger = pm["invalidation_trigger"]
        bull_score, bear_score = pm["bull_score"], pm["bear_score"]
        contested = abs(bull_score - bear_score) < _CONTESTED_MARGIN
        verdict_text = pm["rationale"] or f"{direction.capitalize()} ({conviction}/100 conviction, {time_horizon})."
        confidence = conviction / 100.0
    else:
        # Degraded path: budget-constrained or PM parse failure. Still a
        # real verdict, just the cheaper Bull/Bear/simple-Arbiter shape.
        fallback = _degraded_verdict(ticker, bull, bear, signals)
        verdict_text, confidence = fallback["verdict"], fallback["confidence"]
        direction = "neutral"
        conviction = round(confidence * 100)
        time_horizon, key_risks, invalidation_trigger = None, [], None
        bull_score = bear_score = None
        contested = True  # honest: we don't have the data to say otherwise

    save_market_debate(
        ticker, today, bull, bear, verdict_text, confidence, json.dumps(signals, default=str),
        risk_case=risk_case, direction=direction, conviction=conviction, time_horizon=time_horizon,
        key_risks=json.dumps(key_risks), invalidation_trigger=invalidation_trigger,
        bull_score=bull_score, bear_score=bear_score, contested=contested, est_tokens=est_tokens,
    )
    _log_committee_outcome(ticker, direction)

    return {
        "ticker": ticker, "date": today, "bull_case": bull, "bear_case": bear, "risk_case": risk_case,
        "verdict": verdict_text, "confidence": confidence, "direction": direction, "conviction": conviction,
        "time_horizon": time_horizon, "key_risks": key_risks, "invalidation_trigger": invalidation_trigger,
        "bull_score": bull_score, "bear_score": bear_score, "contested": contested,
        "est_tokens": est_tokens, "cached": False,
    }
