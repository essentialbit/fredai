"""FredAI Scenario Simulator (FSI L3) -- interactive what-if engine.
=====================================
"What if the Fed cuts 50bps?" propagated through Fred's existing
correlation_engine.py/cascade_engine.py data down to portfolio impact.
Reuses cascade_engine.cascade_for_event() for the actual propagation math
(known-relationship + statistical-correlation two-tier walk it already
does) rather than reimplementing it -- this module's job is mapping a
macro shock onto that engine's inputs, adding a second propagation hop,
and overlaying the result on a user's portfolio.

Two shock kinds, kept honestly distinct in the output (same spirit as
cascade_engine's known_relationship vs statistical_correlation split):
- "ticker" factors (WTI, gold, FX, equities, crypto) have real Yahoo price
  history and sit in correlation_matrix -- propagated via
  cascade_for_event() using a real correlation-derived weight.
- "macro_beta" factors (fed funds, 10Y yield, credit OAS, VIX) have no
  tradeable price history in this system, so there is nothing to
  statistically correlate against. These use a small, documented,
  hand-curated sensitivity table instead -- a qualitative expert prior,
  not a statistical claim. Every result says so explicitly.

Regime-conditional correlations (mentioned in the original spec) are not
available -- Regime Detection (a separate FSI Build Playbook feature) has
not shipped. This always uses full-sample correlation and says so in the
assumptions block, per the spec's own documented fallback.

HARD CONSTRAINTS: SQLite-only (no new deps beyond what cascade_engine
already uses); pure-Python math; every result is labeled a model estimate
with an assumptions block; runs must complete <5s (cascade_for_event is
in-memory + cached, no live network call in the propagation path itself).
"""
import re

from cascade_engine import cascade_for_event

SECOND_ORDER_FLOOR = 0.3  # |first-order impact score| below this is dropped before propagating a second hop (noise)
SECOND_ORDER_DAMPEN = 0.5  # extra multiplier applied when re-propagating a first-order impact as a second-order shock
MIN_DISPLAYED_IMPACT = 0.05

# ~12 shockable factors. "ticker" factors propagate through cascade_engine's
# real correlation/relationship data via a proxy ticker; "macro_beta"
# factors use MACRO_BETA below. unit is for display only.
SHOCK_VOCABULARY = {
    "fed_funds":  {"label": "Fed Funds Rate", "unit": "bps", "kind": "macro_beta"},
    "yield_10y":  {"label": "10-Year Treasury Yield", "unit": "bps", "kind": "macro_beta"},
    "credit_oas": {"label": "Credit Spread (OAS)", "unit": "bps", "kind": "macro_beta"},
    "vix":        {"label": "VIX", "unit": "pts", "kind": "macro_beta"},
    "dxy":        {"label": "US Dollar (proxied via EUR/USD, inverted)", "unit": "%",
                    "kind": "ticker", "proxy_ticker": "EURUSD=X", "invert": True},
    "wti":        {"label": "WTI Crude Oil", "unit": "%", "kind": "ticker", "proxy_ticker": "CL=F"},
    "gold":       {"label": "Gold", "unit": "%", "kind": "ticker", "proxy_ticker": "GC=F"},
    "eurusd":     {"label": "EUR/USD", "unit": "%", "kind": "ticker", "proxy_ticker": "EURUSD=X"},
    "audusd":     {"label": "AUD/USD", "unit": "%", "kind": "ticker", "proxy_ticker": "AUDUSD=X"},
    "equities":   {"label": "Broad Equities (S&P 500)", "unit": "%", "kind": "ticker", "proxy_ticker": "SPY"},
    "tech":       {"label": "Tech Sector (Nasdaq 100)", "unit": "%", "kind": "ticker", "proxy_ticker": "QQQ"},
    "bitcoin":    {"label": "Bitcoin", "unit": "%", "kind": "ticker", "proxy_ticker": "BTC-USD"},
}

# Hand-curated sensitivity priors (% estimated move per unit of shock),
# same documented-constant spirit as cascade_engine.IMPACT_WEIGHTS. NOT
# statistical correlations -- there is no price history for these macro
# series to correlate against in this system. Revisit if live scenario
# results don't track analyst intuition; these are directional priors,
# not fitted/backtested figures.
MACRO_BETA = {
    # % move per +100bps (1 percentage point) of the Fed Funds Rate
    "fed_funds": {
        "JPM": 3.0, "GS": 3.0, "BAC": 3.0,
        "QQQ": -6.0, "NVDA": -8.0, "TSLA": -8.0,
        "GC=F": -2.0, "BTC-USD": -6.0,
    },
    # % move per +100bps of the 10Y Treasury yield
    "yield_10y": {
        "JPM": 2.5, "GS": 2.5, "BAC": 2.5,
        "QQQ": -5.0, "NVDA": -7.0, "TSLA": -7.0,
        "GC=F": -1.5,
    },
    # % move per +100bps of credit OAS widening (funding-stress proxy)
    "credit_oas": {
        "SPY": -4.0, "QQQ": -5.0, "TSLA": -6.0, "NVDA": -6.0,
        "GC=F": 2.0, "BTC-USD": -5.0,
    },
    # % move per +1 point of the VIX
    "vix": {
        "SPY": -0.3, "QQQ": -0.4, "TSLA": -0.5, "NVDA": -0.5,
        "BTC-USD": -0.6, "GC=F": 0.15,
    },
}


# ── PROPAGATION ───────────────────────────────────────────────────────────

def _first_order_impacts(factor_key: str, magnitude: float) -> list[dict]:
    spec = SHOCK_VOCABULARY[factor_key]
    if spec["kind"] == "ticker":
        proxy = spec["proxy_ticker"]
        pct = -magnitude if spec.get("invert") else magnitude
        return cascade_for_event(
            proxy, "scenario_shock", pct,
            f"{spec['label']} scenario shock {magnitude:+.1f}{spec['unit']}",
        )

    betas = MACRO_BETA.get(factor_key, {})
    unit_divisor = 100.0 if spec["unit"] == "bps" else 1.0
    results = []
    for sym, beta in betas.items():
        impact = round(beta * (magnitude / unit_divisor), 3)
        if abs(impact) < MIN_DISPLAYED_IMPACT:
            continue
        results.append({
            "symbol": sym, "trigger_symbol": factor_key, "relationship": "macro_beta",
            "strength": None, "impact_score": impact,
            "impact_direction": "positive" if impact > 0 else "negative",
            "impact_severity": "HIGH" if abs(impact) > 3 else "MEDIUM" if abs(impact) > 1 else "LOW",
            "reason": f"{spec['label']} {magnitude:+.0f}{spec['unit']} shock — hand-curated macro "
                      f"sensitivity estimate, not a statistical correlation (no price history for this factor)",
            "data_source": "macro_beta_prior",
        })
    results.sort(key=lambda x: abs(x["impact_score"]), reverse=True)
    return results


def run_scenario(factor_key: str, magnitude: float) -> dict:
    """Propagate one shock through first- and second-order impacts. Second
    order dampens by SECOND_ORDER_DAMPEN on top of whatever weight
    cascade_for_event already applies, and only propagates first-order
    impacts whose |score| clears SECOND_ORDER_FLOOR -- avoids chaining
    noise into more noise."""
    if factor_key not in SHOCK_VOCABULARY:
        return {
            "status": "unmapped",
            "supported_factors": [{"key": k, "label": v["label"], "unit": v["unit"]}
                                   for k, v in SHOCK_VOCABULARY.items()],
        }
    spec = SHOCK_VOCABULARY[factor_key]
    first_order = _first_order_impacts(factor_key, magnitude)
    for r in first_order:
        r["order"] = 1

    # Exclude both the vocabulary key AND (for "ticker" kind factors) the
    # actual proxy ticker -- cascade_for_event's correlation walk is
    # symmetric, so a second-order hop from a first-order-impacted symbol
    # can otherwise loop straight back to the shock's own origin ticker
    # (caught in verification: a WTI shock's second-order pass through USO
    # found CL=F itself as an "impact").
    seen = {r["symbol"] for r in first_order} | {factor_key}
    if spec["kind"] == "ticker":
        seen.add(spec["proxy_ticker"])
    second_order = []
    for r in first_order:
        if abs(r["impact_score"]) < SECOND_ORDER_FLOOR:
            continue
        # r["impact_score"] is already an estimated %-move for r["symbol"]
        # (same units cascade_for_event's own `magnitude` param expects) --
        # feed it in directly, then dampen the RESULTING second-order score.
        # Dampening the magnitude before the call would double-divide it
        # (cascade_for_event's own formula already divides by 10), making
        # every second-order effect vanish under the display floor
        # regardless of correlation strength -- caught in verification.
        for c in cascade_for_event(r["symbol"], "scenario_shock_2nd_order", r["impact_score"],
                                    f"2nd-order propagation via {r['symbol']}"):
            c = dict(c)
            c["impact_score"] = round(c["impact_score"] * SECOND_ORDER_DAMPEN, 3)
            if c["symbol"] in seen or abs(c["impact_score"]) < MIN_DISPLAYED_IMPACT:
                continue
            seen.add(c["symbol"])
            c["order"] = 2
            c["via"] = r["symbol"]
            second_order.append(c)

    impacts = first_order + second_order
    impacts.sort(key=lambda x: abs(x["impact_score"]), reverse=True)
    return {
        "status": "ok", "factor": factor_key, "label": spec["label"],
        "magnitude": magnitude, "unit": spec["unit"],
        "impacts": impacts,
        "assumptions": _assumptions_block(factor_key, spec),
    }


def _assumptions_block(factor_key: str, spec: dict) -> list[str]:
    lines = [
        "This is a model estimate, not a prediction — propagated through historical correlation "
        "strength and hand-curated relationship weights, not a guarantee of actual market behavior.",
    ]
    if spec["kind"] == "macro_beta":
        lines.append(
            f"{spec['label']} has no tradeable price history in this system — impacts use a "
            f"hand-curated sensitivity estimate (qualitative prior), not a statistical correlation."
        )
    else:
        proxy_note = f"{spec['label']} is proxied via {spec['proxy_ticker']}"
        if spec.get("invert"):
            proxy_note += " (inverted — this factor moves opposite to the proxy ticker)"
        lines.append(proxy_note + ".")
    lines.append(
        "First-order impacts use the most recent 30d/90d rolling correlation or a hand-curated "
        "relationship weight; second-order impacts are additionally dampened and carry more uncertainty."
    )
    lines.append(
        "Correlations below |r|=0.3 are excluded as noise. Regime-conditional correlations are not "
        "available (Regime Detection feature not shipped) — this uses full-sample correlation, which "
        "may not reflect current market conditions."
    )
    return lines


# ── PORTFOLIO OVERLAY ─────────────────────────────────────────────────────

# Default breach thresholds -- not user-configurable yet (no such setting
# exists in this codebase; risk_rules.py is proposal-risk tiering, an
# unrelated concept, despite the similar name).
DEFAULT_VAR_THRESHOLD_PCT = 5.0   # 1-day 95% VaR as % of portfolio value
DEFAULT_BETA_THRESHOLD = 1.5      # |beta vs SPY|


def apply_scenario_to_portfolio(impacts: list[dict], positions: list[dict],
                                 baseline_risk: dict | None) -> dict:
    """positions: [{symbol, value, ...}] as produced by
    market_data.calculate_portfolio_value. baseline_risk: the CURRENT
    (pre-scenario) portfolio_risk.compute_portfolio_risk() result, used
    only to flag pre-existing threshold breaches -- this does not attempt
    to recompute VaR/beta under the shocked scenario itself (that would
    need a full historical re-simulation, out of scope for a <5s
    interactive tool)."""
    impact_by_symbol = {i["symbol"]: i["impact_score"] for i in impacts}
    per_position = []
    total_pnl = 0.0
    for p in positions:
        est_pct = impact_by_symbol.get(p["symbol"], 0.0)
        est_pnl = round(p["value"] * (est_pct / 100.0), 2)
        total_pnl += est_pnl
        per_position.append({
            "symbol": p["symbol"], "value": p["value"],
            "estimated_move_pct": round(est_pct, 2), "estimated_pnl": est_pnl,
        })
    per_position.sort(key=lambda x: x["estimated_pnl"])
    worst = per_position[0] if per_position else None

    breach_notes = []
    if baseline_risk and baseline_risk.get("status") == "ok":
        var_pct = baseline_risk.get("var_95_1d_pct")
        beta = baseline_risk.get("beta_spy")
        if var_pct is not None and var_pct > DEFAULT_VAR_THRESHOLD_PCT:
            breach_notes.append(
                f"1-day 95% VaR ({var_pct}%) already exceeds the default {DEFAULT_VAR_THRESHOLD_PCT}% "
                f"threshold before this scenario"
            )
        if beta is not None and abs(beta) > DEFAULT_BETA_THRESHOLD:
            breach_notes.append(
                f"Portfolio beta ({beta}) already exceeds the default ±{DEFAULT_BETA_THRESHOLD} threshold"
            )

    return {
        "total_pnl_estimate": round(total_pnl, 2),
        "per_position": per_position,
        "worst_position": worst,
        "risk_breach_notes": breach_notes,
        "risk_threshold_note": (
            f"Default thresholds (not user-configurable yet): 1-day 95% VaR > "
            f"{DEFAULT_VAR_THRESHOLD_PCT}% of portfolio value, |beta vs SPY| > {DEFAULT_BETA_THRESHOLD}."
        ),
    }


def run_scenario_for_portfolio(factor_key: str, magnitude: float,
                                positions: list[dict] | None, baseline_risk: dict | None = None) -> dict:
    """Top-level entrypoint: run_scenario() plus a portfolio overlay if
    positions are given. positions=None (e.g. empty portfolio) -> no
    overlay, scenario impacts alone are still returned."""
    result = run_scenario(factor_key, magnitude)
    if result["status"] != "ok":
        return result
    if positions:
        result["portfolio"] = apply_scenario_to_portfolio(result["impacts"], positions, baseline_risk)
    else:
        result["portfolio"] = None
    return result


# ── NATURAL-LANGUAGE PARSER ───────────────────────────────────────────────

_DETERMINISTIC_PATTERNS = [
    (re.compile(r"\bfed\s*funds?\b|\brate\s*cuts?\b|\brate\s*hikes?\b|\bfed\s*(cuts?|hikes?)\b", re.I), "fed_funds"),
    (re.compile(r"\b10.?year\b|\b10y\b|\btreasury\s*yields?\b", re.I), "yield_10y"),
    (re.compile(r"\bcredit\s*spreads?\b|\boas\b", re.I), "credit_oas"),
    (re.compile(r"\bvix\b|\bvolatility\s*spikes?\b", re.I), "vix"),
    (re.compile(r"\bdollar\b|\bdxy\b", re.I), "dxy"),
    (re.compile(r"\boil\b|\bwti\b|\bcrude\b", re.I), "wti"),
    (re.compile(r"\bgold\b", re.I), "gold"),
    (re.compile(r"\beuro\b|\beur\b", re.I), "eurusd"),
    (re.compile(r"\baussie\s*dollar\b|\baud\b", re.I), "audusd"),
    (re.compile(r"\bbitcoin\b|\bbtc\b", re.I), "bitcoin"),
    (re.compile(r"\btech\b|\bnasdaq\b|\bqqq\b", re.I), "tech"),
    (re.compile(r"\bmarkets?\b|\bstocks?\b|\bs\W?p\W?500\b|\bspy\b|\bequit", re.I), "equities"),
]
_MAGNITUDE_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(bps|bp|pts?|points?|%)?", re.I)
_DOWN_WORDS_RE = re.compile(r"\bcuts?\b|\bdrops?\b|\bfalls?\b|\bdeclines?\b|\bdown\b|\bplunges?\b", re.I)


def parse_scenario_text(text: str) -> dict | None:
    """Deterministic keyword+number extraction. None if either a factor
    keyword or a numeric magnitude isn't found -- caller falls back to
    the LLM parser rather than guessing."""
    factor = next((key for pattern, key in _DETERMINISTIC_PATTERNS if pattern.search(text)), None)
    if not factor:
        return None
    mag_match = _MAGNITUDE_RE.search(text)
    if not mag_match:
        return None
    magnitude = float(mag_match.group(1))
    if _DOWN_WORDS_RE.search(text) and magnitude > 0:
        magnitude = -magnitude
    return {"factor": factor, "magnitude": magnitude}


_LLM_PARSE_PROMPT = """Extract a market scenario shock from this user question: "{text}"

Valid factors (choose exactly one): {factors}

Respond with ONLY a JSON object, no markdown fences:
{{"factor": "<one of the valid factors above, or null if none apply>", "magnitude": <number>, "direction": "up"|"down"}}"""


def _parse_json(text: str) -> dict | None:
    try:
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        import json
        return json.loads(text)
    except Exception:
        return None


def parse_scenario_llm(text: str) -> dict | None:
    """Cheap-tier LLM fallback, strict-JSON validated against
    SHOCK_VOCABULARY. None (never fabricated/guessed) on any provider
    error, unparseable output, an invalid factor key, or a non-numeric
    magnitude."""
    try:
        from agent import _provider
        prompt = _LLM_PARSE_PROMPT.format(text=text, factors=", ".join(SHOCK_VOCABULARY.keys()))
        raw = _provider.complete(
            [{"role": "user", "content": prompt}],
            "You extract structured market scenarios from natural language. Output strict JSON only.",
            tier="summary", max_tokens=150,
        )
        parsed = _parse_json(raw)
        if not parsed or parsed.get("factor") not in SHOCK_VOCABULARY:
            return None
        magnitude = parsed.get("magnitude")
        if not isinstance(magnitude, (int, float)):
            return None
        magnitude = float(magnitude)
        if parsed.get("direction") == "down" and magnitude > 0:
            magnitude = -magnitude
        return {"factor": parsed["factor"], "magnitude": magnitude}
    except Exception:
        return None


def parse_scenario(text: str) -> dict:
    """Full parse: deterministic first (fast, no LLM cost), LLM fallback,
    then an honest 'I can't model that yet' listing supported factors --
    never a guessed/fabricated mapping."""
    result = parse_scenario_text(text)
    if result:
        return {"status": "ok", "method": "deterministic", **result}
    result = parse_scenario_llm(text)
    if result:
        return {"status": "ok", "method": "llm", **result}
    return {
        "status": "unmapped",
        "supported_factors": [{"key": k, "label": v["label"], "unit": v["unit"]}
                               for k, v in SHOCK_VOCABULARY.items()],
    }
