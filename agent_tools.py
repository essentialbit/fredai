"""Read-only tool belt for Fred's agentic chat (issue #106).

Every tool is a thin wrapper over an EXISTING memory_store/market_data/
technical_alerts function -- no new data paths. The model can only invoke
names present in _EXECUTORS (server-side allowlist); arguments are coerced
and clamped here, never trusted. Strictly read-only: nothing in this module
writes to the database or any external service.
"""
import json

MAX_TOOL_ROUNDS = 4          # tool-call rounds per chat turn (Pi-friendly, bounded latency/cost)
MAX_RESULT_CHARS = 4000      # per-tool-result cap fed back to the model

TOOLS_SYSTEM_NOTE = """

## Live data tools (active in this conversation)
You can call read-only tools that query FredAI's own live database and market
feed: current quotes, price history, stored news, insider (SEC Form 4)
transactions, short interest, sentiment snapshots, Fred's own backtest
accuracy, and technicals (SMA/RSI/volume). Numbers retrieved via tools count
as LIVE CONTEXT -- the never-fabricate rule applies unchanged: if a tool
returns an error or no data, say so plainly instead of inventing a figure.
Prefer a tool call over "I don't have that data" whenever the question is
about something these tools cover but the snapshot above doesn't."""


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default


def _symbol(args: dict, key: str = "symbol") -> str:
    return str(args.get(key, "")).upper().strip()


def _tool_get_quote(args: dict):
    from market_data import fetch_quotes
    sym = _symbol(args)
    if not sym:
        return {"error": "symbol is required"}
    q = fetch_quotes([sym]).get(sym)
    return q if q else {"error": f"no live quote available for {sym} right now"}


# Yahoo's chart API only accepts fixed range tokens -- map a free-form day
# count onto the nearest one instead of passing an invalid "37d" through.
_HISTORY_RANGES = [(5, "5d", "30m"), (30, "1mo", "1d"), (90, "3mo", "1d"),
                   (182, "6mo", "1d"), (365, "1y", "1d"), (99999, "2y", "1wk")]


def _tool_get_history(args: dict):
    from market_data import fetch_history
    sym = _symbol(args)
    if not sym:
        return {"error": "symbol is required"}
    days = _clamp_int(args.get("days"), 1, 730, 30)
    period, interval = next((p, i) for cap, p, i in _HISTORY_RANGES if days <= cap)
    bars = fetch_history(sym, period=period, interval=interval)
    if not bars:
        return {"error": f"no history available for {sym} (feed may be rate-limited)"}
    return {"symbol": sym, "period": period, "interval": interval, "bars": bars[-120:]}


def _tool_query_news(args: dict):
    from memory_store import get_news
    query = str(args.get("query", "")).strip()
    hours = _clamp_int(args.get("hours"), 1, 168, 24)
    items = get_news(ticker=query or None, hours=hours, limit=10)
    if not items:
        return {"note": f"no stored news matching '{query}' in the last {hours}h"}
    keep = ("title", "source", "category", "tickers", "sentiment_score", "published_at", "url")
    return {"query": query, "hours": hours,
            "items": [{k: it.get(k) for k in keep if it.get(k) is not None} for it in items]}


def _tool_get_insider_transactions(args: dict):
    from memory_store import get_recent_insider_transactions
    sym = _symbol(args, "ticker") or _symbol(args)
    if not sym:
        return {"error": "ticker is required"}
    days = _clamp_int(args.get("days"), 1, 365, 90)
    rows = get_recent_insider_transactions(sym, days=days)
    if not rows:
        return {"note": f"no signal-grade insider transactions stored for {sym} in the last {days} days"}
    return {"ticker": sym, "days": days, "transactions": rows[:15]}


def _tool_get_short_interest(args: dict):
    from memory_store import get_latest_short_interest, get_short_interest_direction
    sym = _symbol(args)
    if not sym:
        return {"error": "symbol is required"}
    latest = get_latest_short_interest(sym)
    if not latest:
        return {"note": f"no short-interest data stored for {sym}"}
    latest["trend_direction"] = get_short_interest_direction(sym)
    return latest


def _tool_get_sentiment_snapshot(args: dict):
    from memory_store import get_sentiment_snapshot
    sym = _symbol(args)
    if not sym:
        return {"error": "symbol is required"}
    hours = _clamp_int(args.get("hours"), 1, 168, 24)
    snap = get_sentiment_snapshot([sym], hours=hours).get(sym)
    return {"symbol": sym, "hours": hours, **snap} if snap else \
        {"note": f"no sentiment signals for {sym} in the last {hours}h"}


def _tool_get_backtest_accuracy(args: dict):
    from memory_store import get_backtest_accuracy, _OUTCOME_CHECKPOINTS
    checkpoint = str(args.get("checkpoint", "24h"))
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        checkpoint = "24h"
    return get_backtest_accuracy(checkpoint=checkpoint)


def _tool_get_technicals(args: dict):
    from technical_alerts import get_technicals
    sym = _symbol(args)
    if not sym:
        return {"error": "symbol is required"}
    t = get_technicals(sym)
    return t if t else {"error": f"no price data available for {sym} right now"}


_EXECUTORS = {
    "get_quote": _tool_get_quote,
    "get_history": _tool_get_history,
    "query_news": _tool_query_news,
    "get_insider_transactions": _tool_get_insider_transactions,
    "get_short_interest": _tool_get_short_interest,
    "get_sentiment_snapshot": _tool_get_sentiment_snapshot,
    "get_backtest_accuracy": _tool_get_backtest_accuracy,
    "get_technicals": _tool_get_technicals,
}


def execute_tool(name: str, args: dict | None) -> str:
    """Allowlisted dispatch. Always returns a string (JSON when possible),
    never raises -- tool failures go back to the model as data."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        result = fn(args or {})
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    text = json.dumps(result, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... [truncated]'
    return text


def _num(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def _sym_prop(desc: str = "Ticker symbol, e.g. NVDA or BTC-USD") -> dict:
    return {"type": "string", "description": desc}


# Canonical specs in Anthropic tool format; converted for other providers below.
TOOL_SPECS = [
    {
        "name": "get_quote",
        "description": "Current live price, change % and day stats for one symbol.",
        "input_schema": {"type": "object", "properties": {"symbol": _sym_prop()},
                         "required": ["symbol"]},
    },
    {
        "name": "get_history",
        "description": "Historical OHLCV price bars for a symbol over the last N days (max 730).",
        "input_schema": {"type": "object",
                         "properties": {"symbol": _sym_prop(),
                                        "days": _num("Lookback window in days (default 30)")},
                         "required": ["symbol"]},
    },
    {
        "name": "query_news",
        "description": "Search stored financial news headlines by ticker or keyword within the last N hours (max 168 -- older news is pruned).",
        "input_schema": {"type": "object",
                         "properties": {"query": {"type": "string", "description": "Ticker or keyword to match in headlines"},
                                        "hours": _num("Lookback in hours (default 24)")},
                         "required": ["query"]},
    },
    {
        "name": "get_insider_transactions",
        "description": "Recent SEC Form 4 insider transactions (signal-grade buys/sells) stored for a US ticker.",
        "input_schema": {"type": "object",
                         "properties": {"ticker": _sym_prop("US stock ticker, e.g. NVDA"),
                                        "days": _num("Lookback in days (default 90)")},
                         "required": ["ticker"]},
    },
    {
        "name": "get_short_interest",
        "description": "Latest stored short interest (% of float, short ratio) and its trend direction for a symbol.",
        "input_schema": {"type": "object", "properties": {"symbol": _sym_prop()},
                         "required": ["symbol"]},
    },
    {
        "name": "get_sentiment_snapshot",
        "description": "Aggregated signal sentiment (avg score, bullish/bearish lean, signal count) for a symbol over the last N hours.",
        "input_schema": {"type": "object",
                         "properties": {"symbol": _sym_prop(),
                                        "hours": _num("Lookback in hours (default 24)")},
                         "required": ["symbol"]},
    },
    {
        "name": "get_backtest_accuracy",
        "description": "Fred's own measured prediction accuracy: how often predicted signal direction matched the actual price move, per source, vs a naive momentum baseline. Use when asked about Fred's track record or credibility.",
        "input_schema": {"type": "object",
                         "properties": {"checkpoint": {"type": "string", "enum": ["4h", "24h", "72h"],
                                                       "description": "Horizon the prediction was scored at (default 24h)"}}},
    },
    {
        "name": "get_technicals",
        "description": "Technical indicators for a symbol: SMA20, SMA50, RSI14, volume and volume ratio vs 20-day average.",
        "input_schema": {"type": "object", "properties": {"symbol": _sym_prop()},
                         "required": ["symbol"]},
    },
]


def anthropic_tools() -> list[dict]:
    return TOOL_SPECS


def gemini_tool_declarations() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "parameters": t["input_schema"]} for t in TOOL_SPECS]


def openai_tools() -> list[dict]:
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["input_schema"]}} for t in TOOL_SPECS]
