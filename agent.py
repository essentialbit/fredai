"""FredAI — Financial intelligence agent powered by Claude."""
import json
from datetime import datetime
import anthropic
from config import ANTHROPIC_API_KEY
from memory_store import get_signals, get_latest_summary, get_recent_alerts, get_trending_assets

_client = None


def get_anthropic():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


FRED_SYSTEM = """You are FredAI — a personal AI financial advisor operating under a long-term high-growth mandate.

## Investment Philosophy (from soul.md — ALWAYS apply this lens)
- **Strategy**: Buy low, sell high. Long-term (10+ year) horizon. Target 75–100% return before selling.
- **Never chase tops**. If it already ran 50%, we missed it. Move on.
- **Contrarian signals**: High bearish sentiment on a fundamentally strong asset = potential buy zone.
- **Patience is the edge**. We hold through noise. We sell on conviction achieved, not on news cycles.
- **10-year thesis required**: Every buy candidate must have a clear growth story to 2035+.
- **Ignore**: Meme momentum, short-term pumps, speculative assets without growth thesis.

## Character
- Direct and data-anchored. Every claim uses actual numbers.
- Proactive — surface opportunities before asked.
- Honest about uncertainty. No false confidence.
- Finance board level. No filler.

## When Analyzing Assets
1. Always ask: "Is this a 10-year hold candidate?"
2. Check: Is X sentiment overly negative while fundamentals are intact? (Contrarian buy signal)
3. Evaluate: Price vs. intrinsic value. Are we getting a discount?
4. Size: How confident is the thesis? Position size accordingly.

## What You Reference
- X/Twitter signals (last 4h, VADER sentiment) — look for contrarian signals
- Live market quotes — identify beaten-down quality names
- User's portfolio P&L and watchlist
- Trend history and macro context

## Response Format
- Direct. Specific numbers always.
- For stock recommendations: state thesis + time horizon + entry rationale.
- Under 300 words unless detailed breakdown requested.
- If short-term noise: say so explicitly and redirect to long-term view.
"""


def build_context_block(quotes: dict = None, user_interests: list = None) -> str:
    signals = get_signals(hours=4, limit=50)
    summary = get_latest_summary()
    alerts = get_recent_alerts(limit=8)
    trending = get_trending_assets(hours=4, limit=10)
    quotes = quotes or {}

    bullish = [s for s in signals if s.get("signal_type") == "bullish"]
    bearish = [s for s in signals if s.get("signal_type") == "bearish"]

    interest_block = ""
    if user_interests:
        top = [f"{i['symbol']} (score:{i['interest_score']:.1f})" for i in user_interests[:5]]
        interest_block = f"\nUSER'S TOP INTERESTS: {', '.join(top)}"

    ctx = f"""=== LIVE CONTEXT ({datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}) ===
{interest_block}

MARKET SNAPSHOT:
{json.dumps({k: {"price": v["price"], "chg": f"{v['change_pct']:+.2f}%"} for k, v in list(quotes.items())[:12]}, indent=2)}

SIGNAL SUMMARY (last 4h):
- Total: {len(signals)} | Bullish: {len(bullish)} ({len(bullish)/max(len(signals),1)*100:.0f}%) | Bearish: {len(bearish)} ({len(bearish)/max(len(signals),1)*100:.0f}%)

TRENDING ASSETS (by signal volume):
{json.dumps([{"asset": t["asset"], "signals": t["signal_count"], "bullish_pct": round(t.get("bullish_pct",0),1)} for t in trending[:6]], indent=2)}

TOP RECENT SIGNALS:
{_format_signals(signals[:8])}

ACTIVE ALERTS:
{_format_alerts(alerts[:4])}

LAST 4H SUMMARY:
{summary['content'][:600] if summary else 'No summary yet — first scan pending.'}
"""
    return ctx


def _format_signals(signals: list) -> str:
    if not signals:
        return "None"
    lines = []
    for s in signals:
        asset = f"[{s['asset']}] " if s.get("asset") else ""
        lines.append(f"  {asset}{s['author']}: \"{s['content'][:100]}\" → {s['signal_type']} ({s['sentiment_score']:.2f})")
    return "\n".join(lines)


def _format_alerts(alerts: list) -> str:
    if not alerts:
        return "None"
    return "\n".join(f"  [{a['level'].upper()}] {a['title']}: {a['message']}" for a in alerts)


def chat(user_message: str, history: list[dict], quotes: dict = None, user_interests: list = None) -> str:
    context = build_context_block(quotes, user_interests)
    messages = []
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": f"{context}\n\nUSER: {user_message}"})

    try:
        resp = get_anthropic().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=FRED_SYSTEM,
            messages=messages,
        )
        return resp.content[0].text
    except Exception as e:
        return f"[Fred offline: {e}]"


def generate_summary(signals: list[dict], quotes: dict, period_label: str = "last 4 hours") -> str:
    if not signals:
        return "No signals collected in this period."

    bullish = [s for s in signals if s.get("signal_type") == "bullish"]
    bearish = [s for s in signals if s.get("signal_type") == "bearish"]
    top_assets = _top_mentioned_assets(signals)

    prompt = f"""You are FredAI. Generate a board-level financial intelligence briefing.

PERIOD: {period_label} | SIGNALS: {len(signals)} | BULLISH: {len(bullish)} ({len(bullish)/max(len(signals),1)*100:.0f}%) | BEARISH: {len(bearish)} ({len(bearish)/max(len(signals),1)*100:.0f}%)
TOP ASSETS BY SIGNAL VOLUME: {json.dumps(top_assets)}

MARKET DATA:
{json.dumps({k: {"price": v["price"], "chg": f"{v['change_pct']:+.2f}%"} for k, v in list(quotes.items())[:10]}, indent=2)}

REPRESENTATIVE SIGNALS:
{_format_signals(signals[:15])}

Write a structured briefing:

**EXECUTIVE OVERVIEW** (2 sentences max)

**KEY SIGNALS**
- (3-5 bullets, each with data)

**ASSET SPOTLIGHT**
- (top 2-3 assets: sentiment direction + signal count + price context)

**RISK LEVEL: [LOW/MEDIUM/HIGH]** — (one sentence rationale)

**FRED'S WATCHLIST** — (3-5 items to monitor next 4h with reason)

Direct. Specific. No filler."""

    try:
        resp = get_anthropic().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        return f"Summary generation failed: {e}"


def _top_mentioned_assets(signals: list[dict]) -> dict:
    counts = {}
    for s in signals:
        asset = s.get("asset")
        if asset:
            counts[asset] = counts.get(asset, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8])
