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
catalyst sources -- both have since merged and are now wired in below as
`_central_bank_catalyst` (macro-wide, like `_macro_catalyst`) and
`_options_catalyst` (per-symbol positioning shift).
"""
from datetime import date

from memory_store import (
    get_recent_insider_transactions,
    get_calendar_events_window,
    get_news,
    get_latest_correlation_matrix,
    get_latest_central_bank_delta,
    get_options_data_prior_pair,
)

CORRELATION_WINDOWS = (30, 90)
MIN_ABS_CORRELATION = 0.5
NEWS_LOOKBACK_HOURS = 48
INSIDER_LOOKBACK_DAYS = 7
MACRO_EVENT_TYPES = {"fomc", "fomc_press_conference", "rba", "macro"}
CENTRAL_BANK_LOOKBACK_DAYS = 3
MIN_SENTIMENT_DELTA = 0.1
MIN_IV_JUMP_PCT = 5.0
MIN_PC_RATIO_SHIFT = 0.3


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


def _central_bank_catalyst():
    """Macro-wide, symbol-agnostic -- like _macro_catalyst, but keyed off a
    real detected sentiment shift between consecutive FOMC statements rather
    than just the meeting's presence on the calendar. Only fires within
    CENTRAL_BANK_LOOKBACK_DAYS of the meeting, since a stale delta from
    months back isn't a catalyst for today's move."""
    delta = get_latest_central_bank_delta("Fed")
    if delta.get("status") == "no_data":
        return None
    sentiment_delta = delta.get("sentiment_delta")
    meeting_date = delta.get("meeting_date")
    if sentiment_delta is None or not meeting_date:
        return None
    try:
        days_since = (date.today() - date.fromisoformat(meeting_date)).days
    except ValueError:
        return None
    if not (0 <= days_since <= CENTRAL_BANK_LOOKBACK_DAYS):
        return None
    if abs(sentiment_delta) < MIN_SENTIMENT_DELTA:
        return None
    direction = "negative" if sentiment_delta < 0 else "positive"
    excerpt = ""
    changed = delta.get("changed_paragraphs") or []
    if changed:
        added = " ".join(changed[0].get("added_words", [])[:8])
        removed = " ".join(changed[0].get("removed_words", [])[:8])
        if added and removed:
            excerpt = f' -- e.g. added "{added}", removed "{removed}"'
        elif added:
            excerpt = f' -- e.g. added "{added}"'
        elif removed:
            excerpt = f' -- e.g. removed "{removed}"'
    return {
        "source": "central_bank",
        "description": (
            f"FOMC statement ({meeting_date}) tone shifted {direction} "
            f"(sentiment delta {sentiment_delta:+.2f}){excerpt}"
        ),
        "date": meeting_date,
        "weight": min(0.4 + abs(sentiment_delta) * 0.6, 0.65),
    }


def _options_catalyst(symbol: str):
    """Per-symbol options-positioning shift between the two most recent
    snapshots -- a jump in ATM IV or a swing in the put/call ratio signals a
    change in how the market is pricing/hedging the name, distinct from (and
    often faster-moving than) the news/insider catalysts above."""
    pair = get_options_data_prior_pair(symbol)
    if not pair:
        return None
    latest, prior = pair
    signals = []
    weight = 0.0

    iv_now, iv_prior = latest.get("atm_iv_pct"), prior.get("atm_iv_pct")
    if iv_now is not None and iv_prior is not None:
        iv_jump = iv_now - iv_prior
        if abs(iv_jump) >= MIN_IV_JUMP_PCT:
            signals.append(f"ATM IV {iv_jump:+.1f}pt to {iv_now:.1f}%")
            weight = max(weight, min(0.2 + abs(iv_jump) * 0.02, 0.5))

    pc_now, pc_prior = latest.get("put_call_volume_ratio"), prior.get("put_call_volume_ratio")
    if pc_now is not None and pc_prior is not None and pc_prior > 0:
        pc_shift = (pc_now - pc_prior) / pc_prior
        if abs(pc_shift) >= MIN_PC_RATIO_SHIFT:
            direction = "bearish" if pc_shift > 0 else "bullish"
            signals.append(
                f"put/call volume ratio {pc_shift * 100:+.0f}% to {pc_now:.2f} "
                f"({direction} positioning shift)"
            )
            weight = max(weight, min(0.2 + abs(pc_shift) * 0.3, 0.5))

    if not signals:
        return None
    return {
        "source": "options_positioning",
        "description": "; ".join(signals),
        "date": latest.get("fetched_at"),
        "weight": weight,
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
        (_central_bank_catalyst, ()),
        (_insider_catalyst, (symbol,)),
        (_news_catalyst, (symbol,)),
        (_options_catalyst, (symbol,)),
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
