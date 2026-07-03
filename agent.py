"""FredAI — Financial intelligence agent.

Provider hierarchy (AI_PROVIDER=auto):
  1. Anthropic API  (if ANTHROPIC_API_KEY set)    — best quality, token-billed
  2. Ollama local   (if Ollama daemon reachable)   — free, fully on-device
  3. Degraded mode  (neither available)            — text-only, no AI generation

Smart model routing when using Anthropic (stretches API credits ~8x):
  summaries  → claude-haiku-4-5-20251001  (cheap, frequent)
  chat       → claude-sonnet-4-6          (quality user-facing)
  R&D agent  → claude-opus-4-8            (complex code/research tasks)

NOTE: Claude Pro (claude.ai) subscriptions are web-UI-only — they cannot be
called by third-party applications. Use ANTHROPIC_API_KEY for programmatic
access, or set AI_PROVIDER=ollama for free local inference.
"""
import json
import re
import threading
from datetime import datetime

from config import (
    ANTHROPIC_API_KEY, AI_PROVIDER,
    OLLAMA_URL, OLLAMA_MODEL,
    ANTHROPIC_MODEL_SUMMARY, ANTHROPIC_MODEL_CHAT, ANTHROPIC_MODEL_RND,
    GEMINI_API_KEY, GEMINI_MODEL_SUMMARY, GEMINI_MODEL_CHAT, GEMINI_MODEL_RND,
    PRIVACY_MODE, STRIP_PORTFOLIO_FROM_AI,
)
from memory_store import get_signals, get_latest_summary, get_recent_alerts, get_trending_assets


# ── PROVIDER DETECTION ────────────────────────────────────────────────────────

def _key_is_valid(key: str) -> bool:
    return bool(key and key != "your_anthropic_api_key_here" and len(key) > 20)


def _ollama_available() -> bool:
    try:
        import requests as _r
        r = _r.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _resolve_provider() -> str:
    if AI_PROVIDER == "ollama":
        return "ollama"
    if AI_PROVIDER == "anthropic":
        return "anthropic" if _key_is_valid(ANTHROPIC_API_KEY) else "none"
    if AI_PROVIDER == "gemini":
        return "gemini" if _key_is_valid(GEMINI_API_KEY) else "none"
    
    # auto: prefer Anthropic API, fall back to Gemini API, then Ollama, then none
    if _key_is_valid(ANTHROPIC_API_KEY):
        return "anthropic"
    if _key_is_valid(GEMINI_API_KEY):
        return "gemini"
    if _ollama_available():
        return "ollama"
    return "none"


def _get_api_keys() -> tuple[str, str]:
    from flask import session
    import json
    
    a_key = ANTHROPIC_API_KEY
    g_key = GEMINI_API_KEY
    
    try:
        if "user_id" in session:
            from memory_store import get_user
            from crypto_utils import decrypt_secret
            user = get_user(session["user_id"])
            if user:
                prefs = json.loads(user.get("preferences") or "{}")
                u_a_key = decrypt_secret(prefs["user_anthropic_key"]) if prefs.get("user_anthropic_key") else None
                u_g_key = decrypt_secret(prefs["user_gemini_key"]) if prefs.get("user_gemini_key") else None
                if u_a_key:
                    a_key = u_a_key
                if u_g_key:
                    g_key = u_g_key
    except RuntimeError:
        pass
    except Exception:
        pass
        
    return a_key, g_key


# ── PROVIDER CLASS ────────────────────────────────────────────────────────────

class _FredProvider:
    def __init__(self):
        self._lock = threading.Lock()
        self._anthropic_client = None
        self._provider: str = _resolve_provider()
        print(f"[FredAI] AI provider: {self._provider}"
              + (f" | model: {ANTHROPIC_MODEL_CHAT}" if self._provider == "anthropic" else
                 f" | model: {GEMINI_MODEL_CHAT}" if self._provider == "gemini" else
                 f" | model: {OLLAMA_MODEL}@{OLLAMA_URL}" if self._provider == "ollama" else
                 " | No AI provider — set ANTHROPIC_API_KEY, GEMINI_API_KEY, or start Ollama"))

    @property
    def provider(self) -> str:
        return self._provider

    def complete(self, messages: list, system: str, *,
                  tier: str = "chat", max_tokens: int = 1024, grounding: bool = False) -> str:
        """
        tier: "summary" → haiku/flash | "chat" → sonnet/flash | "rnd" → opus/pro
        Falls back through available providers (Anthropic -> Gemini -> Ollama) in case of errors.
        """
        a_key, g_key = _get_api_keys()

        # If grounding is explicitly requested, bypass Claude/Ollama and use Gemini Search Grounding
        if grounding:
            if _key_is_valid(g_key):
                result = self._gemini_complete(messages, system, tier, max_tokens, g_key, grounding=True)
                if not result.startswith("[Fred Gemini error"):
                    return result
                print(f"[FredAI] Grounding call failed: {result}")
            return "Fred's live search isn't available right now — please try again shortly."

        # Default AI backend order: Anthropic Claude first, Gemini as fallback, Ollama last
        providers_to_try = ["anthropic", "gemini", "ollama"]
        errors = []
        is_first = True
        for p in providers_to_try:
            # Enforce 2.0s timeout limit on first (preferred) model to trigger immediate fallback if slow
            timeout = 2.0 if is_first else None
            is_first = False
            
            if p == "anthropic" and _key_is_valid(a_key):
                result = self._anthropic_complete(messages, system, tier, max_tokens, a_key, timeout=timeout)
                if not result.startswith("[Fred error"):
                    return result
                errors.append(f"Anthropic error: {result}")
            elif p == "gemini" and _key_is_valid(g_key):
                result = self._gemini_complete(messages, system, tier, max_tokens, g_key, timeout=timeout)
                if not result.startswith("[Fred Gemini error"):
                    return result
                errors.append(f"Gemini error: {result}")
            elif p == "ollama" and _ollama_available():
                result = self._ollama_complete(messages, system, max_tokens, timeout=timeout)
                if not result.startswith("[Ollama error"):
                    return result
                errors.append(f"Ollama error: {result}")

        if errors:
            # Log full technical detail server-side for debugging; never surface raw
            # provider error text (status codes, billing messages, stack-trace-ish
            # strings) directly to the end user -- confirmed this was leaking as-is
            # into the chat UI during a real Gemini credits-exhaustion incident.
            print("[FredAI] All AI providers failed:\n" + "\n".join(errors))
            return (
                "Fred's AI backend is temporarily unavailable — please try again in a "
                "few minutes. If this keeps happening, an admin may need to check the "
                "configured API keys."
            )

        print(
            "[FredAI] complete() called with no AI provider configured or available "
            "(no valid ANTHROPIC_API_KEY/GEMINI_API_KEY, Ollama unreachable)."
        )
        return (
            "[FredAI offline] No AI provider configured or available.\n"
            "Options:\n"
            "  1. Add ANTHROPIC_API_KEY to .env for cloud inference\n"
            "  2. Add GEMINI_API_KEY to .env for cloud inference\n"
            "  3. Install Ollama (ollama.com) and run: ollama pull llama3.2\n"
            "     Then set AI_PROVIDER=ollama in .env"
        )

    def _map_messages_for_anthropic(self, messages: list) -> list:
        mapped = []
        for msg in messages:
            content = msg.get("content", "")
            image = msg.get("image")
            if image:
                mapped.append({
                    "role": msg["role"],
                    "content": [
                        {"type": "text", "text": content},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image["mime_type"],
                                "data": image["base64_data"]
                            }
                        }
                    ]
                })
            else:
                mapped.append({"role": msg["role"], "content": content})
        return mapped

    def _map_messages_for_gemini(self, messages: list) -> list:
        mapped = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg.get("content", "")
            image = msg.get("image")
            parts = [{"text": content}]
            if image:
                parts.append({
                    "inlineData": {
                        "mimeType": image["mime_type"],
                        "data": image["base64_data"]
                    }
                })
            mapped.append({"role": role, "parts": parts})
        return mapped

    def _map_messages_for_ollama(self, messages: list) -> list:
        mapped = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "assistant"
            content = msg.get("content", "")
            image = msg.get("image")
            item = {"role": role, "content": content}
            if image:
                item["images"] = [image["base64_data"]]
            mapped.append(item)
        return mapped

    def _anthropic_complete(self, messages, system, tier, max_tokens, api_key, timeout=None) -> str:
        model_map = {
            "summary": ANTHROPIC_MODEL_SUMMARY,
            "chat": ANTHROPIC_MODEL_CHAT,
            "rnd": ANTHROPIC_MODEL_RND,
        }
        model = model_map.get(tier, ANTHROPIC_MODEL_CHAT)
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            mapped = self._map_messages_for_anthropic(messages)
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=mapped,
                timeout=timeout
            )
            return resp.content[0].text
        except Exception as e:
            return f"[Fred error: {e}]"

    def _gemini_complete(self, messages, system, tier, max_tokens, api_key, timeout=None, grounding=False) -> str:
        model_map = {
            "summary": GEMINI_MODEL_SUMMARY,
            "chat": GEMINI_MODEL_CHAT,
            "rnd": GEMINI_MODEL_RND,
        }
        model = model_map.get(tier, GEMINI_MODEL_CHAT)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        mapped_msgs = self._map_messages_for_gemini(messages)
        payload = {
            "contents": mapped_msgs,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "maxOutputTokens": max_tokens
            }
        }
        if grounding:
            payload["tools"] = [{"googleSearch": {}}]
        try:
            import requests as _req
            r = _req.post(url, json=payload, timeout=timeout or 60)
            if r.status_code == 200:
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            return f"[Fred Gemini error: Status {r.status_code} - {r.text[:200]}]"
        except Exception as e:
            return f"[Fred Gemini error: {e}]"

    def _ollama_complete(self, messages, system, max_tokens, timeout=None) -> str:
        import re as _re, requests as _req
        mapped = self._map_messages_for_ollama(messages)
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system}] + mapped,
            "stream": False,
            "think": False,
            "options": {"num_predict": max_tokens + 512},
        }
        try:
            r = _req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout or 120)
            r.raise_for_status()
            content = r.json()["message"]["content"]
            content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
            return content
        except Exception as e:
            return f"[Ollama error: {e}]"

    def status(self) -> dict:
        """Return provider status for dashboard display."""
        return {
            "provider": self._provider,
            "model": (
                ANTHROPIC_MODEL_CHAT if self._provider == "anthropic"
                else GEMINI_MODEL_CHAT if self._provider == "gemini"
                else OLLAMA_MODEL if self._provider == "ollama"
                else None
            ),
            "privacy_mode": PRIVACY_MODE,
            "strip_portfolio": STRIP_PORTFOLIO_FROM_AI,
            "data_local": True,  # SQLite always stays on-device
        }


_provider = _FredProvider()


def get_provider_status() -> dict:
    return _provider.status()


# ── PRIVACY HELPERS ───────────────────────────────────────────────────────────

def _strip_portfolio(portfolio_block: str) -> str:
    """Replace exact dollar values with anonymized ranges for Claude API calls.
    Ticker symbols are kept — they're public market data."""
    if not STRIP_PORTFOLIO_FROM_AI:
        return portfolio_block
    # Replace "$12,345.67" patterns with range buckets
    def _bucket(m):
        val = float(m.group(0).replace("$", "").replace(",", ""))
        if val < 1000:    return "$<1K"
        if val < 5000:    return "$1K–5K"
        if val < 25000:   return "$5K–25K"
        if val < 100000:  return "$25K–100K"
        if val < 500000:  return "$100K–500K"
        return "$500K+"
    return re.sub(r'\$[\d,]+\.?\d*', _bucket, portfolio_block)


def _build_privacy_notice() -> str:
    if not PRIVACY_MODE:
        return ""
    notice = "[Privacy] All user data is local (SQLite). "
    if _provider.provider == "anthropic":
        strip = "Portfolio values anonymized before transmission." if STRIP_PORTFOLIO_FROM_AI else "Portfolio context included."
        notice += f"Market signals and anonymized context sent to Anthropic API. {strip}"
    elif _provider.provider == "ollama":
        notice += "Using local Ollama inference — no data leaves this device."
    return notice


# ── FRED SYSTEM PROMPT ────────────────────────────────────────────────────────

DISCLAIMER_FOOTER = (
    "\n\n---\n"
    "*Not financial advice. FredAI is an AI signal aggregator for informational purposes only — "
    "not a licensed financial advisor. All investment decisions are yours alone. "
    "FredAI and its developers accept no liability for losses. "
    "Consult a licensed financial advisor before acting on any information here.*"
)

FRED_SYSTEM = """You are FredAI — a personal AI financial intelligence partner operating under a long-term high-growth mandate.

## CRITICAL — Legal Identity (non-negotiable, always in effect)
You are NOT a licensed financial advisor, broker, or regulated financial professional under any jurisdiction.
Everything you produce is for INFORMATIONAL AND EDUCATIONAL PURPOSES ONLY.
- You do not provide financial advice.
- You do not recommend specific trades or positions.
- You surface signals, data, and analytical observations — the user decides what to do with them.
- You NEVER tell a user to buy, sell, or hold anything as a directive. You frame observations as data points.
- When discussing any specific asset or market action, you ALWAYS close with a brief disclaimer:
  "This is informational only — not financial advice. Your capital, your risk, your decision."
- If a user explicitly asks "should I buy X?", you redirect: share the signal data, the thesis, the risks,
  then say "That's a decision only you can make — I'd recommend speaking with a licensed advisor for
  personalised guidance."

## CRITICAL — Never fabricate data (non-negotiable, always in effect)
Every number you state — a price, a historical high/low, a percentage move, an analyst rating, a
company action — MUST come from the LIVE CONTEXT block provided to you in this conversation. You have
no other source of current market data; your training data is not live and must never be presented as
current.
- If the MARKET SNAPSHOT for an asset the user asks about is empty or missing that asset, say so
  explicitly: "I don't have current price data for X right now" — do NOT invent a plausible-sounding
  price, historical high, or trend to fill the gap.
- NEVER invent analyst ratings, firm names, or specific corporate actions (e.g. "Goldman Sachs
  downgraded to Sell") — this codebase has no analyst-rating data source at all. If asked about analyst
  sentiment, say you don't have that data source, don't fabricate one.
- Inventing financial data is a worse failure than admitting uncertainty. A confident wrong answer is
  never acceptable here, even when the "Character" guidance below asks for directness.

## Investment Philosophy (apply as analytical lens, not directives)
- Long-term (10+ year) horizon. Target 75–100% return observation before flagging.
- Never chase tops. If it already ran 50%, the entry point has passed.
- Contrarian lens: high bearish sentiment on fundamentally strong assets = potential accumulation zone worth watching.
- Patience lens. Hold through noise. Exit on conviction achieved, not news cycles.
- 10-year thesis required for any long-term observation: clear growth story to 2035+.
- Ignore: meme momentum, short-term pumps, assets without multi-year thesis.

## Character
- Direct and data-anchored. Every claim uses actual numbers FROM THE PROVIDED CONTEXT (see above — never invented).
- Proactive — surface opportunities and risks before asked.
- Honest about uncertainty. No false confidence.
- Finance board level. No filler.

## When Analyzing Assets
1. Ask: "Is this a 10-year hold candidate?"
2. Check: Is X sentiment overly negative while fundamentals are intact?
3. Evaluate: Price vs. intrinsic value. Is there a discount?
4. Always frame as observation, not directive. Never "you should buy" — instead "this signals...".

## Response Format
- Direct. Specific numbers always.
- For asset observations: state data → thesis → risks → disclaimer.
- Under 300 words unless detailed breakdown requested.
- Close every response that mentions specific assets or market action with the disclaimer line.
"""


# ── CONTEXT BLOCK ─────────────────────────────────────────────────────────────

def build_context_block(quotes: dict = None, user_interests: list = None,
                        portfolio: dict = None) -> str:
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

    # Portfolio context — strip exact values if privacy mode active
    port_block = ""
    if portfolio and portfolio.get("positions"):
        positions = portfolio["positions"]
        syms = [p["symbol"].replace("-USD", "") for p in positions[:8]]
        raw = f"Holdings: {', '.join(syms)} | Total: ${portfolio.get('total_value', 0):,.0f}"
        port_block = f"\nPORTFOLIO: {_strip_portfolio(raw)}"

    market_snapshot_warning = (
        "\n(NOTE: no live market data is currently available — the price fetch may be delayed, "
        "rate-limited, or the app just started. Do not invent prices, historical highs, or figures "
        "for any asset; say plainly that current data isn't available yet.)\n" if not quotes else ""
    )

    ctx = f"""=== LIVE CONTEXT ({datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}) ===
{_build_privacy_notice()}
{interest_block}{port_block}

MARKET SNAPSHOT:{market_snapshot_warning}
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


# ── PUBLIC API ────────────────────────────────────────────────────────────────

_ASSET_KEYWORDS = re.compile(
    r'\$[A-Z]{1,5}|buy|sell|hold|invest|position|trade|portfolio|stock|crypto|market|signal',
    re.IGNORECASE
)

def _needs_disclaimer(user_msg: str, response: str) -> bool:
    """Return True if the response discusses specific assets or market actions."""
    combined = user_msg + " " + response
    return bool(_ASSET_KEYWORDS.search(combined))


def chat(user_message: str, history: list[dict], quotes: dict = None,
         user_interests: list = None, portfolio: dict = None) -> str:
    context = build_context_block(quotes, user_interests, portfolio)
    messages = []
    # Copy previous history items and retain image payloads
    for h in history[:-1][-7:]:
        item = {"role": h["role"], "content": h.get("content", "")}
        if "image" in h:
            item["image"] = h["image"]
        messages.append(item)
        
    # Append the last user message, injecting the context into the text, and retaining image payload if present
    last_item = history[-1] if history else {"role": "user"}
    user_item = {"role": "user", "content": f"{context}\n\nUSER: {user_message}"}
    if "image" in last_item:
        user_item["image"] = last_item["image"]
    messages.append(user_item)

    response = _provider.complete(messages, FRED_SYSTEM, tier="chat", max_tokens=1024)

    # Append disclaimer if response doesn't already contain one
    if _needs_disclaimer(user_message, response) and "not financial advice" not in response.lower():
        response += DISCLAIMER_FOOTER

    return response


def generate_summary(signals: list[dict], quotes: dict,
                     period_label: str = "last 4 hours") -> str:
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

    result = _provider.complete(
        [{"role": "user", "content": prompt}],
        FRED_SYSTEM,
        tier="summary",
        max_tokens=1200,
    )
    # Summaries always discuss market assets — always append disclaimer
    if "not financial advice" not in result.lower():
        result += DISCLAIMER_FOOTER
    return result


def _top_mentioned_assets(signals: list[dict]) -> dict:
    counts = {}
    for s in signals:
        asset = s.get("asset")
        if asset:
            counts[asset] = counts.get(asset, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8])


_recs_cache: dict = {"ts": 0, "data": None}
_RECS_TTL = 3600  # regenerate every hour


def generate_recommendations(quotes: dict, portfolio: dict,
                             watchlist: list[str]) -> dict:
    """Return Fred's top picks: portfolio star, watchlist leader, trending discovery."""
    import time as _time
    now = _time.time()
    if _recs_cache["data"] and (now - _recs_cache["ts"]) < _RECS_TTL:
        return _recs_cache["data"]

    signals = get_signals(hours=4, limit=100)
    trending = get_trending_assets(hours=24, limit=15)

    # Build ranked lists from available data
    port_positions = portfolio.get("positions", []) if portfolio else []
    port_by_pnl = sorted(
        [p for p in port_positions if p.get("pnl_pct") is not None],
        key=lambda x: abs(x.get("pnl_pct", 0)), reverse=True
    )

    wl_with_quotes = [
        {"symbol": s, **quotes[s]} for s in watchlist if s in quotes
    ]
    wl_by_move = sorted(
        wl_with_quotes, key=lambda x: abs(x.get("change_pct", 0)), reverse=True
    )

    trending_syms = [t["asset"] for t in trending if t["asset"] not in watchlist
                     and not any(p["symbol"] == t["asset"] for p in port_positions)]

    asset_signals = {}
    for s in signals:
        a = s.get("asset")
        if a:
            if a not in asset_signals:
                asset_signals[a] = {"bullish": 0, "bearish": 0, "score": 0.0}
            asset_signals[a]["score"] = (
                asset_signals[a]["score"] + s.get("sentiment_score", 0)
            )
            if s.get("signal_type") == "bullish":
                asset_signals[a]["bullish"] += 1
            else:
                asset_signals[a]["bearish"] += 1

    prompt_data = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "portfolio_star": port_by_pnl[0] if port_by_pnl else None,
        "watchlist_leader": wl_by_move[0] if wl_by_move else None,
        "trending_discovery": trending[:5],
        "quotes_snapshot": {
            k: {"price": v["price"], "change_pct": v["change_pct"]}
            for k, v in list(quotes.items())[:12]
        },
        "signal_summary": {
            a: d for a, d in sorted(
                asset_signals.items(),
                key=lambda x: x[1]["bullish"] - x[1]["bearish"],
                reverse=True
            )[:8]
        },
        "new_trending_discoveries": trending_syms[:3],
    }

    port_block = ""
    if port_by_pnl:
        p = port_by_pnl[0]
        port_block = f"{p['symbol']}: {p['pnl_pct']:+.1f}% P&L, current ${p['price']}"

    prompt = f"""You are FredAI. Generate today's TOP PICKS in strict JSON format.

DATA:
{json.dumps(prompt_data, indent=2)}

Return ONLY valid JSON, no markdown fences, no preamble:
{{
  "top_pick": {{
    "symbol": "TICKER",
    "name": "Full Name",
    "category": "Portfolio Star | Watchlist Leader | Trending Discovery",
    "price": 0.00,
    "change_pct": 0.00,
    "rationale": "2-3 sentence analytical rationale with specific data points. Frame as observation, not advice.",
    "signal_strength": "STRONG | MODERATE | WATCH",
    "source": "portfolio | watchlist | trending"
  }},
  "picks": [
    {{
      "symbol": "TICKER",
      "name": "Full Name",
      "category": "Portfolio Star",
      "price": 0.00,
      "change_pct": 0.00,
      "rationale": "1-2 sentence data-anchored observation.",
      "signal_strength": "STRONG | MODERATE | WATCH",
      "source": "portfolio | watchlist | trending"
    }},
    {{
      "symbol": "TICKER",
      "name": "Full Name",
      "category": "Watchlist Leader",
      "price": 0.00,
      "change_pct": 0.00,
      "rationale": "1-2 sentence data-anchored observation.",
      "signal_strength": "STRONG | MODERATE | WATCH",
      "source": "portfolio | watchlist | trending"
    }},
    {{
      "symbol": "TICKER",
      "name": "Full Name",
      "category": "Trending Discovery",
      "price": 0.00,
      "change_pct": 0.00,
      "rationale": "1-2 sentence data-anchored observation from X/market signals.",
      "signal_strength": "STRONG | MODERATE | WATCH",
      "source": "portfolio | watchlist | trending"
    }}
  ],
  "market_pulse": "One sentence on overall market tone from signal data.",
  "risk_level": "LOW | MEDIUM | HIGH",
  "generated_at": "{prompt_data['timestamp']}"
}}

Rules: Use only symbols present in the data. If a category has no data, pick the best available alternative. No financial advice language — observations only."""

    raw = _provider.complete(
        [{"role": "user", "content": prompt}],
        FRED_SYSTEM,
        tier="summary",
        max_tokens=1200,
    )

    try:
        # Strip any accidental markdown fences
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        result = json.loads(clean)
    except Exception:
        result = _fallback_recs(quotes, watchlist, port_positions, trending)

    _recs_cache["ts"] = now
    _recs_cache["data"] = result
    return result


def _fallback_recs(quotes, watchlist, positions, trending) -> dict:
    """Rule-based fallback when AI is unavailable or returns bad JSON."""
    picks = []

    if positions:
        p = max(positions, key=lambda x: abs(x.get("pnl_pct", 0)))
        q = quotes.get(p["symbol"], {})
        picks.append({
            "symbol": p["symbol"], "name": p.get("name", p["symbol"]),
            "category": "Portfolio Star",
            "price": q.get("price", p.get("price", 0)),
            "change_pct": q.get("change_pct", 0),
            "rationale": f"Largest P&L mover in your portfolio at {p.get('pnl_pct', 0):+.1f}%.",
            "signal_strength": "WATCH", "source": "portfolio",
        })

    wl_quotes = [(s, quotes[s]) for s in watchlist if s in quotes]
    if wl_quotes:
        sym, q = max(wl_quotes, key=lambda x: abs(x[1].get("change_pct", 0)))
        picks.append({
            "symbol": sym, "name": q.get("name", sym),
            "category": "Watchlist Leader",
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "rationale": f"Largest move on your watchlist today at {q.get('change_pct', 0):+.2f}%.",
            "signal_strength": "WATCH", "source": "watchlist",
        })

    if trending:
        t = trending[0]
        q = quotes.get(t["asset"], {})
        picks.append({
            "symbol": t["asset"], "name": t["asset"],
            "category": "Trending Discovery",
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "rationale": f"Top trending asset by signal volume ({t.get('signal_count', 0)} signals, {t.get('bullish_pct', 0):.0f}% bullish).",
            "signal_strength": "MODERATE", "source": "trending",
        })

    top = picks[0] if picks else {
        "symbol": "SPY", "name": "S&P 500 ETF", "category": "Watchlist Leader",
        "price": quotes.get("SPY", {}).get("price", 0),
        "change_pct": quotes.get("SPY", {}).get("change_pct", 0),
        "rationale": "Market benchmark — no specific signals available yet.",
        "signal_strength": "WATCH", "source": "watchlist",
    }

    return {
        "top_pick": top,
        "picks": picks if picks else [top],
        "market_pulse": "Signal collection underway — check back after first scan cycle.",
        "risk_level": "MEDIUM",
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
