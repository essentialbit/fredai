"""
Cascade Alert Engine — forward-propagation intelligence.

When a major event fires on a stock (price move, earnings, high-impact news),
traverse the relationship graph to identify downstream-affected companies and
generate derivative alerts ranked by impact severity.

Data-quality note (2026-07-04): the qualitative relationship graph below
(EDGES) is a small, hand-curated list -- real and useful for the ~135
tickers it covers, but not comprehensive, and it doesn't update itself.
Cascade now also draws on the correlation_matrix (30d/90d rolling Pearson
correlation, computed from real price history -- see correlation_engine.py)
as a second, statistically-grounded data source, so a major move on a
ticker with no hand-typed relationship still produces cascade coverage
where the real data supports it. The two sources are kept honestly
distinct in the output (relationship="correlated" vs a named business
relationship) rather than conflated -- "these two move together" is a
different, weaker claim than "X is Y's supplier," and presenting them
identically would overstate what the correlation data actually tells you.
"""
import time
from datetime import datetime
from graph_engine import EDGES, SECTORS, SECTOR_COLORS, EDGE_COLORS
from memory_store import get_latest_correlation_matrix

PRICE_MOVE_THRESHOLD = 3.0    # % move that triggers cascade
NEWS_SENTIMENT_THRESHOLD = 0.7
MIN_ABS_CORRELATION = 0.5     # below this, a correlation is too noisy to alert on

# Relationship impact weights: how much of the trigger's move propagates
IMPACT_WEIGHTS = {
    "supplier":    0.80,
    "customer":    0.60,
    "partner":     0.65,
    "subsidiary":  0.90,
    "investor":    0.50,
    "ecosystem":   0.40,
    "government":  0.30,
    "regulatory":  0.35,
    "musk-linked": 0.40,
    "australia":   0.20,
    "competitor":  0.50,  # handled as inverse below
}


def _build_adjacency() -> dict:
    adj: dict = {}
    for src, tgt, etype, strength, desc in EDGES:
        if src == tgt:
            continue
        adj.setdefault(src, []).append(
            {"symbol": tgt, "type": etype, "strength": strength, "desc": desc}
        )
        adj.setdefault(tgt, []).append(
            {"symbol": src, "type": etype, "strength": strength, "desc": desc}
        )
    return adj


_ADJ = _build_adjacency()

_cascade_cache: dict = {}
_CASCADE_TTL = 300


def _correlation_neighbors(symbol: str, known_symbols: set) -> list[dict]:
    """Statistically-correlated tickers not already covered by the hand-typed
    EDGES relationship graph. Prefers the 30d window (more responsive to
    current market regime); falls back to 90d only for pairs the 30d window
    doesn't cover. Returns [] gracefully if the correlation job hasn't run
    yet (empty table) -- no fabricated relationships."""
    symbol = symbol.upper()
    seen_pairs = set()
    results = []
    for window in (30, 90):
        for pair in get_latest_correlation_matrix(window):
            a, b, corr = pair["symbol_a"], pair["symbol_b"], pair["correlation"]
            if symbol not in (a, b) or abs(corr) < MIN_ABS_CORRELATION:
                continue
            other = b if a == symbol else a
            if other in known_symbols or other in seen_pairs:
                continue  # already covered by a real relationship, or already found at a shorter window
            seen_pairs.add(other)
            direction = "move together" if corr > 0 else "move inversely"
            results.append({
                "symbol": other,
                "type": "correlated",
                "strength": round(abs(corr) * 10, 1),
                "corr_value": corr,
                "desc": f"Statistically {direction} ({window}d correlation: {corr:+.2f}) -- not a confirmed business relationship",
            })
    return results


def cascade_for_event(symbol: str, event_type: str, magnitude: float,
                      description: str) -> list[dict]:
    """
    Given a major event on `symbol`, return a ranked list of affected companies.

    Each result: {symbol, relationship, impact_score, impact_direction,
                  impact_severity, reason, edge_color, sector, sector_color}
    """
    cache_key = f"{symbol}:{event_type}:{round(magnitude, 1)}"
    cached = _cascade_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CASCADE_TTL:
        return cached["cascades"]

    neighbors = _ADJ.get(symbol.upper(), [])
    known_symbols = {n["symbol"] for n in neighbors}
    cascades = []

    for n in neighbors:
        rel = n["type"]
        strength_norm = n["strength"] / 10.0
        weight = IMPACT_WEIGHTS.get(rel, 0.3)

        if rel == "competitor":
            # One competitor's loss is the other's gain
            impact_score = -weight * strength_norm * (magnitude / 10.0)
            impact_direction = "positive" if magnitude < 0 else "negative"
        else:
            impact_score = weight * strength_norm * (magnitude / 10.0)
            impact_direction = "negative" if magnitude < 0 else "positive"

        if abs(impact_score) < 0.04:
            continue

        reason = _build_reason(symbol, n["symbol"], rel, event_type, magnitude, n["desc"])
        sector = SECTORS.get(n["symbol"], "Other")

        cascades.append({
            "symbol": n["symbol"],
            "trigger_symbol": symbol,
            "relationship": rel,
            "strength": n["strength"],
            "impact_score": round(impact_score, 3),
            "impact_direction": impact_direction,
            "impact_severity": (
                "HIGH" if abs(impact_score) > 0.5
                else "MEDIUM" if abs(impact_score) > 0.2
                else "LOW"
            ),
            "reason": reason,
            "edge_desc": n["desc"],
            "edge_color": EDGE_COLORS.get(rel, "#4a6380"),
            "sector": sector,
            "sector_color": SECTOR_COLORS.get(sector, "#4a6380"),
            "data_source": "known_relationship",
            "generated_at": datetime.utcnow().isoformat(),
        })

    # Statistically-correlated tickers the hand-typed graph doesn't cover.
    # Uses the real correlation coefficient directly as the propagation
    # weight -- correlation's sign already encodes co-movement direction, so
    # this needs no hand-tuned IMPACT_WEIGHTS entry the way named
    # relationship types do.
    for n in _correlation_neighbors(symbol, known_symbols):
        impact_score = n["corr_value"] * (magnitude / 10.0)
        if abs(impact_score) < 0.04:
            continue
        impact_direction = "positive" if impact_score > 0 else "negative"
        sector = SECTORS.get(n["symbol"], "Other")
        cascades.append({
            "symbol": n["symbol"],
            "trigger_symbol": symbol,
            "relationship": "correlated",
            "strength": n["strength"],
            "impact_score": round(impact_score, 3),
            "impact_direction": impact_direction,
            "impact_severity": (
                "HIGH" if abs(impact_score) > 0.5
                else "MEDIUM" if abs(impact_score) > 0.2
                else "LOW"
            ),
            "reason": f"{symbol} {'decline' if magnitude < 0 else 'surge'} ({magnitude:+.1f}%) -- {n['desc']}",
            "edge_desc": n["desc"],
            "edge_color": EDGE_COLORS.get("correlated", "#8ba3b8"),
            "sector": sector,
            "sector_color": SECTOR_COLORS.get(sector, "#4a6380"),
            "data_source": "statistical_correlation",
            "generated_at": datetime.utcnow().isoformat(),
        })

    cascades.sort(key=lambda x: abs(x["impact_score"]), reverse=True)
    _cascade_cache[cache_key] = {"ts": time.time(), "cascades": cascades}
    return cascades


def _build_reason(trigger: str, affected: str, rel: str, event_type: str,
                  magnitude: float, edge_desc: str) -> str:
    direction = "decline" if magnitude < 0 else "surge"
    if rel == "supplier":
        return f"{trigger} {direction} ({magnitude:+.1f}%) impacts {affected} as a customer — {edge_desc}"
    elif rel == "customer":
        return f"{trigger} {direction} flows through to {affected} as a supplier — {edge_desc}"
    elif rel == "competitor":
        gain = "tailwind" if magnitude < 0 else "headwind"
        return f"{trigger} {direction} may be a {gain} for competitor {affected} — {edge_desc}"
    elif rel == "partner":
        return f"{affected} has significant partnership exposure: {edge_desc}"
    elif rel == "subsidiary":
        return f"{affected} directly impacted as subsidiary — {edge_desc}"
    elif rel == "ecosystem":
        return f"{affected} shares ecosystem with {trigger}: {edge_desc}"
    else:
        return f"{affected} connected ({rel}) to {trigger}: {edge_desc}"


def detect_major_moves(quotes: dict) -> list[dict]:
    """Return symbols with moves >= PRICE_MOVE_THRESHOLD."""
    events = []
    for sym, q in quotes.items():
        chg = q.get("change_pct", 0)
        if abs(chg) >= PRICE_MOVE_THRESHOLD:
            events.append({
                "symbol": sym,
                "event_type": "price_move",
                "magnitude": chg,
                "description": f"{sym} moved {chg:+.2f}%",
                "severity": "HIGH" if abs(chg) > 5 else "MEDIUM",
                "price": q.get("price", 0),
            })
    return sorted(events, key=lambda x: abs(x["magnitude"]), reverse=True)


def run_cascade_check(quotes: dict) -> list[dict]:
    """Top-level: check quotes, cascade all major events. Returns list of {trigger, cascades}."""
    results = []
    for event in detect_major_moves(quotes):
        cascades = cascade_for_event(
            event["symbol"], event["event_type"],
            event["magnitude"], event["description"]
        )
        if cascades:
            results.append({
                "trigger": event,
                "cascades": cascades[:6],
            })
    return results
