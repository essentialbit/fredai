"""Adversarial multi-agent ticker debate panel (FSI L4).

Directly implements the MISSION.md L4 roadmap item: "Multi-agent market
debate (Bull Agent vs Bear Agent, synthesised by Arbiter)" -- a spec'd,
previously-unbuilt capability, not a new idea.

Three role prompts run through agent.py's existing _FredProvider (Claude
-> Gemini -> Grok -> Groq -> Ollama fallback already implemented there)
rather than hand-rolling provider calls. debate.py has its own direct
per-provider calls because it runs outside the Flask app (CI/community
context); this module runs inside it, so the shared provider abstraction
in agent.py is the right fit, not a duplicate of debate.py's pattern.

Cost control: 3 LLM calls per run, so verdicts are cached per ticker
(see memory_store.get_latest_ticker_debate) rather than recomputed on
every request.
"""
import json

from agent import _provider
from technical_alerts import get_technicals
from memory_store import get_news, insert_ticker_debate, get_latest_ticker_debate
from fear_greed_client import fetch_fear_greed
from copper_gold_ratio import get_copper_gold_ratio
from sector_rotation import get_sector_rotation

_CACHE_TTL_S = 21600  # 6h, matches the other 6h-cadence jobs (job_agent_debate, job_correlation)

_BULL_PROMPT = """You are the Bull analyst on FredAI's adversarial market debate panel.

TICKER: {ticker}
TECHNICALS: {technicals}
RECENT NEWS: {news}

Argue the long/bullish thesis for {ticker} as persuasively as the actual evidence \
allows. Be specific and cite the technicals/news given -- never fabricate data not \
provided above.

Respond with ONLY a JSON object, no markdown fences:
{{"thesis": "2-4 sentences", "key_points": ["...", "..."], "conviction": 0.0-1.0}}"""

_BEAR_PROMPT = """You are the Bear analyst on FredAI's adversarial market debate panel.

TICKER: {ticker}
TECHNICALS: {technicals}
RECENT NEWS: {news}

Argue the short/bearish thesis for {ticker} as persuasively as the actual evidence \
allows. Be specific and cite the technicals/news given -- never fabricate data not \
provided above.

Respond with ONLY a JSON object, no markdown fences:
{{"thesis": "2-4 sentences", "key_points": ["...", "..."], "conviction": 0.0-1.0}}"""

_MODERATOR_PROMPT = """You are the Macro Moderator on FredAI's adversarial market debate \
panel, synthesising a Bull and a Bear thesis for {ticker} into one calibrated verdict.

BULL THESIS: {bull}
BEAR THESIS: {bear}
CURRENT MACRO REGIME: {macro}

Weigh both theses against the current macro regime context above. Don't just average \
the two scores -- if the macro backdrop clearly favors one side, say so and reflect it \
in the confidence.

Respond with ONLY a JSON object, no markdown fences:
{{"consensus": "bullish"|"bearish"|"neutral", "confidence": 0.0-1.0, "bull_score": 0.0-1.0, \
"bear_score": 0.0-1.0, "rationale": "2-4 sentences"}}"""

_VALID_CONSENSUS = ("bullish", "bearish", "neutral")


def _parse_json(text: str) -> dict | None:
    try:
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        return json.loads(text)
    except Exception:
        return None


def _macro_context() -> dict:
    fg = fetch_fear_greed()
    cg = get_copper_gold_ratio()
    sr = get_sector_rotation()
    return {
        "fear_greed": {"score": fg.get("score"), "rating": fg.get("rating")} if fg else None,
        "copper_gold_regime": cg.get("regime") if cg else None,
        "sector_rotation": sr or None,
    }


def run_ticker_debate(ticker: str) -> dict | None:
    """Run one Bull/Bear/Moderator cycle for ticker, persist + return the
    scorecard. None (never a fabricated result) if any role's response
    isn't parseable JSON."""
    technicals = get_technicals(ticker)
    news_items = get_news(ticker=ticker, hours=24, limit=10)
    news_summary = "; ".join((n.get("content") or "")[:100] for n in news_items[:5]) or "no recent news"

    bull_raw = _provider.complete(
        messages=[{"role": "user", "content": _BULL_PROMPT.format(
            ticker=ticker, technicals=technicals, news=news_summary)}],
        system="You are a rigorous, evidence-based bull-case equity analyst.",
        tier="chat", max_tokens=400,
    )
    bull = _parse_json(bull_raw)
    if not bull:
        return None

    bear_raw = _provider.complete(
        messages=[{"role": "user", "content": _BEAR_PROMPT.format(
            ticker=ticker, technicals=technicals, news=news_summary)}],
        system="You are a rigorous, evidence-based bear-case equity analyst.",
        tier="chat", max_tokens=400,
    )
    bear = _parse_json(bear_raw)
    if not bear:
        return None

    macro = _macro_context()
    verdict_raw = _provider.complete(
        messages=[{"role": "user", "content": _MODERATOR_PROMPT.format(
            ticker=ticker, bull=bull, bear=bear, macro=macro)}],
        system="You are a neutral, macro-aware moderator synthesising two adversarial "
               "analyst theses into one calibrated verdict.",
        tier="chat", max_tokens=400,
    )
    verdict = _parse_json(verdict_raw)
    if not verdict or verdict.get("consensus") not in _VALID_CONSENSUS or "confidence" not in verdict:
        return None

    debate_id = insert_ticker_debate(ticker, bull, bear, verdict)
    _index_debate_for_recall(debate_id, ticker, bull, bear, verdict)
    return {"ticker": ticker, "bull": bull, "bear": bear, "verdict": verdict}


def _index_debate_for_recall(debate_id: int, ticker: str, bull: dict, bear: dict, verdict: dict) -> None:
    """Fred Recall write-time hook -- FTS-only (embed=False), the nightly
    embed-backlog job picks up embeddings later. Never blocks/fails the
    caller."""
    try:
        from rag_store import upsert_chunk
        content = (
            f"BULL: {bull.get('case', '')}\nBEAR: {bear.get('case', '')}\n"
            f"VERDICT: {verdict.get('consensus', '')} (confidence {verdict.get('confidence', '')})"
        )
        upsert_chunk(
            "debate", str(debate_id), content, title=f"{ticker} Bull/Bear debate",
            tickers=ticker, embed=False,
        )
    except Exception:
        pass


def get_ticker_debate(ticker: str, force: bool = False) -> dict | None:
    """Cached accessor -- reuses the latest persisted debate if it's
    within _CACHE_TTL_S, otherwise runs a fresh panel."""
    if not force:
        cached = get_latest_ticker_debate(ticker, max_age_s=_CACHE_TTL_S)
        if cached:
            return cached
    return run_ticker_debate(ticker)
