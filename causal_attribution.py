"""
Causal attribution for major price moves.

MISSION.md's L4 list names this directly ("BTC fell because: Fed minutes +
CPI surprise, not crypto-native"). cascade_engine.detect_major_moves() flags
*which* symbols moved, but nothing ranked *why* -- Fred's chat had to fall
back on vague prompt-stuffed narrative, the same fabrication risk class
already rejected once for the #31 chat-hallucination fix and the Google
Studio concept repo's invented-news pattern (2026-07-02).

Deterministic (no LLM call) synthesis over data FredAI already ingests and
stores -- ranks candidate catalysts, never invents one. An empty result with
an honest "no clear catalyst" summary is a valid, correct output.

Deliberately built only on sources already merged to main. The original
proposal (#145) also named central_bank_client.py (#144, semantic FOMC-
statement deltas) and options_data_client.py (#128, put/call + IV shifts) as
catalyst sources -- neither is merged yet, same "build on what's actually on
main, not an unmerged sibling branch" call already made for #135's Bull/Bear
debate agents. Both are natural follow-on sources once their PRs land.
"""
from memory_store import (
    get_recent_insider_transactions,
    get_calendar_events_window,
    get_news,
    get_latest_correlation_matrix,
)

CORRELATION_WINDOWS = (30, 90)
MIN_ABS_CORRELATION = 0.5
NEWS_LOOKBACK_HOURS = 48
INSIDER_LOOKBACK_DAYS = 7
MACRO_EVENT_TYPES = {"fomc", "fomc_press_conference", "rba", "macro"}


def _earnings_catalyst(symbol: str):
    events = get_calendar_events_window(symbol=symbol, event_type="earnings",
                                        days_back=2, days_forward=1)
    if not events:
        return None
    ev = events[0]
    return {
        "source": "earnings_calendar",
        "description": f"{ev['title']} ({ev['event_date']})",
        "date": ev["event_date"],
        "weight": 0.75,
    }


def _macro_catalyst():
    events = get_calendar_events_window(days_back=1, days_forward=0)
    hits = [e for e in events
            if e.get("event_type") in MACRO_EVENT_TYPES
            and str(e.get("importance", "")).upper() in ("HIGH", "CRITICAL")]
    if not hits:
        return None
    ev = hits[0]
    return {
        "source": "macro_calendar",
        "description": f"{ev['title']} ({ev['event_date']})",
        "date": ev["event_date"],
        "weight": 0.55,
    }


def _insider_catalyst(symbol: str):
    txns = get_recent_insider_transactions(symbol, days=INSIDER_LOOKBACK_DAYS, signal_only=True)
    if not txns:
        return None
    buys = sum(1 for t in txns if t.get("acquired_disposed") == "A")
    sells = sum(1 for t in txns if t.get("acquired_disposed") == "D")
    direction = "buying" if buys > sells else "selling" if sells > buys else "activity"
    names = sorted({t["owner_name"] for t in txns if t.get("owner_name")})[:3]
    who = ", ".join(names) if names else "insiders"
    return {
        "source": "insider_form4",
        "description": f"{len(txns)} insider {direction} filing(s) in the last {INSIDER_LOOKBACK_DAYS}d ({who})",
        "date": txns[0].get("transaction_date"),
        "weight": min(0.3 + 0.1 * len(txns), 0.7),
    }


def _news_catalyst(symbol: str):
    recent = get_news(ticker=symbol, hours=NEWS_LOOKBACK_HOURS, limit=50)
    if len(recent) < 2:
        return None
    scores = [n.get("sentiment_score") or 0 for n in recent]
    avg = sum(scores) / len(scores)
    if abs(avg) < 0.25:
        return None
    top = max(recent, key=lambda n: abs(n.get("sentiment_score") or 0))
    return {
        "source": "news",
        "description": (
            f"{len(recent)} headline(s) in {NEWS_LOOKBACK_HOURS}h, avg sentiment {avg:+.2f} "
            f'-- e.g. "{top["title"]}" ({top.get("source", "unknown")})'
        ),
        "date": top.get("published_at"),
        "weight": min(0.2 + abs(avg) * 0.4, 0.6),
    }


def _correlation_catalyst(symbol: str, quotes: dict):
    """Same-direction neighbor that moved at least as hard -- sector/macro
    contagion, not a confirmed business catalyst. Kept honestly labeled as
    weaker than the named-source catalysts above, same distinction
    cascade_engine._correlation_neighbors already draws for cascades."""
    if not quotes:
        return None
    symbol = symbol.upper()
    self_chg = quotes.get(symbol, {}).get("change_pct", 0)
    best = None
    for window in CORRELATION_WINDOWS:
        for pair in get_latest_correlation_matrix(window):
            a, b, corr = pair["symbol_a"], pair["symbol_b"], pair["correlation"]
            if symbol not in (a, b) or abs(corr) < MIN_ABS_CORRELATION:
                continue
            other = b if a == symbol else a
            other_q = quotes.get(other)
            if not other_q:
                continue
            other_chg = other_q.get("change_pct", 0)
            same_direction = corr > 0 and (other_chg * self_chg) > 0
            if not same_direction or abs(other_chg) < abs(self_chg) * 0.5:
                continue
            weight = min(abs(corr) * 0.5, 0.5)
            if not best or weight > best["weight"]:
                best = {
                    "source": "correlation",
                    "description": (
                        f"{other} moved {other_chg:+.1f}% ({window}d correlation: {corr:+.2f}) "
                        "-- possible sector/macro contagion, not a confirmed catalyst"
                    ),
                    "date": None,
                    "weight": weight,
                }
    return best


def attribute_move(symbol: str, event_type: str = "price_move", magnitude: float = 0.0,
                   quotes: dict = None) -> dict:
    """Rank candidate catalysts for a flagged price move from already-ingested
    sources. Returns {"catalysts": [...], "summary": str} -- never a
    fabricated narrative. Each catalyst dict is retrievable from a
    already-merged data source; an empty list with an honest "no clear
    catalyst" summary is a valid result, not a failure."""
    symbol = symbol.upper()
    candidates = []
    for fn, args in (
        (_earnings_catalyst, (symbol,)),
        (_macro_catalyst, ()),
        (_insider_catalyst, (symbol,)),
        (_news_catalyst, (symbol,)),
        (_correlation_catalyst, (symbol, quotes)),
    ):
        try:
            c = fn(*args)
        except Exception:
            c = None
        if c:
            candidates.append(c)

    candidates.sort(key=lambda c: c["weight"], reverse=True)
    summary = candidates[0]["description"] if candidates else "No clear catalyst found in tracked sources."
    return {"symbol": symbol, "event_type": event_type, "magnitude": magnitude,
            "catalysts": candidates, "summary": summary}
