"""
Cascade Alert Engine — forward-propagation intelligence.

When a major event fires on a stock (price move, earnings, high-impact news),
traverse the relationship graph to identify downstream-affected companies and
generate derivative alerts ranked by impact severity.
"""
import time
from datetime import datetime
from graph_engine import EDGES, SECTORS, SECTOR_COLORS, EDGE_COLORS

PRICE_MOVE_THRESHOLD = 3.0    # % move that triggers cascade
NEWS_SENTIMENT_THRESHOLD = 0.7

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
