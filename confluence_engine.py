"""Signal confluence score — synthesizes Fred's existing independent signal
sources (sentiment, insider transactions, short-interest trend, technical
momentum) into one higher-order read per symbol.

Deliberately not a new data source (MISSION.md Guiding Principle #2/#3):
every factor here is already computed and stored elsewhere. This module only
asks "do the independent factors already agree?" -- the same multi-factor
confluence pattern institutional desks use, applied to data Fred already has.

Only reports factors that actually have data (Principle #7 — no fabricated
neutral/placeholder factors). A symbol with zero qualifying factors returns
status "no_data", never a fake score.
"""
import time

from memory_store import (
    get_sentiment_snapshot,
    get_recent_insider_transactions,
    get_short_interest_direction,
    get_calibration_weight,
)

MIN_FACTORS_FOR_ALERT = 3  # "full confluence" alert threshold — 2 agreeing is common, 3+ is the rare high-signal case
_CACHE_TTL = 6 * 3600  # matches the 6h scan/refresh cadence that produces the underlying factors

# confluence factor name -> calibration_engine/backtesting_engine source
# name. "sentiment" here is the broadest available sentiment snapshot
# (get_sentiment_snapshot); the closest calibrated source is
# backtesting_engine's "news_sentiment" (reads news_items directly) --
# an imperfect but reasonable correspondence, not an exact same-query match.
_CALIBRATION_SOURCE_MAP = {"sentiment": "news_sentiment"}

_cache: dict[str, tuple[float, dict]] = {}


def _sentiment_factor(symbol: str) -> dict | None:
    snap = get_sentiment_snapshot([symbol], hours=24, min_real=1).get(symbol)
    if not snap or snap["signal_type"] == "neutral":
        return None
    return {
        "direction": snap["signal_type"],
        "detail": f"{snap['signal_count']} signal(s), avg sentiment {snap['avg_sentiment']:+.2f}",
    }


def _insider_factor(symbol: str) -> dict | None:
    txns = get_recent_insider_transactions(symbol, days=90, signal_only=True)
    if not txns:
        return None
    buys = sum(1 for t in txns if t["signal_type"] == "open_market_purchase")
    sells = sum(1 for t in txns if t["signal_type"] == "open_market_sale")
    if buys == sells:
        return None
    return {
        "direction": "bullish" if buys > sells else "bearish",
        "detail": f"{buys} insider buy(s) vs {sells} sell(s) (90d)",
    }


def _short_interest_factor(symbol: str) -> dict | None:
    direction = get_short_interest_direction(symbol)
    if not direction:
        return None
    detail = "short ratio falling — covering" if direction == "bullish" else "short ratio rising — growing bearish bet"
    return {"direction": direction, "detail": detail}


def _technical_factor(symbol: str) -> dict | None:
    """Network-bound (fetches price history) -- callers on latency-sensitive
    paths (chat context) should skip this and rely on the cache instead."""
    from technical_alerts import get_technicals
    tech = get_technicals(symbol)
    current, sma20, sma50 = tech.get("current"), tech.get("sma20"), tech.get("sma50")
    if not (current and sma20 and sma50):
        return None
    if current > sma20 > sma50:
        return {"direction": "bullish", "detail": f"price>{sma20:.2f}(SMA20)>{sma50:.2f}(SMA50)"}
    if current < sma20 < sma50:
        return {"direction": "bearish", "detail": f"price<{sma20:.2f}(SMA20)<{sma50:.2f}(SMA50)"}
    return None


def compute_confluence(symbol: str, include_technical: bool = True) -> dict:
    """Real-time computation. include_technical=True hits the network
    (price history) -- pass False on latency-sensitive paths."""
    factors = {}
    for name, fn in (
        ("sentiment", _sentiment_factor),
        ("insider", _insider_factor),
        ("short_interest", _short_interest_factor),
    ):
        f = fn(symbol)
        if f:
            factors[name] = f
    if include_technical:
        f = _technical_factor(symbol)
        if f:
            factors["technical"] = f

    if not factors:
        return {"status": "no_data", "symbol": symbol}

    # Agreement/factor_count are always raw, unweighted counts -- "full
    # confluence" is a structural fact (do the independent sources agree),
    # not something calibration should change. Only the continuous `score`
    # is reliability-weighted, and only behind the flag -- with it off,
    # score is bit-identical to the pre-calibration formula.
    bullish = sum(1 for f in factors.values() if f["direction"] == "bullish")
    bearish = sum(1 for f in factors.values() if f["direction"] == "bearish")
    total = len(factors)

    from config import CALIBRATION_WEIGHTS_ENABLED
    if CALIBRATION_WEIGHTS_ENABLED:
        def _w(name):
            return get_calibration_weight(_CALIBRATION_SOURCE_MAP.get(name, name))
        w_bull = sum(_w(name) for name, f in factors.items() if f["direction"] == "bullish")
        w_bear = sum(_w(name) for name, f in factors.items() if f["direction"] == "bearish")
        w_total = sum(_w(name) for name in factors)
        score = round((w_bull - w_bear) / w_total, 2) if w_total else 0.0
    else:
        score = round((bullish - bearish) / total, 2)

    if total >= 2 and (bullish == total or bearish == total):
        agreement = "full_confluence"
    elif bullish > 0 and bearish > 0:
        agreement = "conflicting"
    else:
        agreement = "partial"

    return {
        "status": "ok",
        "symbol": symbol,
        "score": score,
        "direction": "bullish" if score > 0 else "bearish" if score < 0 else "neutral",
        "agreement": agreement,
        "factor_count": total,
        "factors": factors,
    }


def refresh_confluence(symbols: list[str]) -> list[dict]:
    """Recompute (with technicals) and cache confluence for each symbol.
    Returns the subset that reached full agreement across >= MIN_FACTORS_FOR_ALERT
    factors -- the genuinely alert-worthy cases."""
    alertable = []
    now = time.time()
    for sym in symbols:
        result = compute_confluence(sym, include_technical=True)
        _cache[sym] = (now, result)
        if (result.get("status") == "ok" and result["agreement"] == "full_confluence"
                and result["factor_count"] >= MIN_FACTORS_FOR_ALERT):
            alertable.append(result)
    return alertable


def get_cached_confluence(symbol: str) -> dict | None:
    hit = _cache.get(symbol)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def format_confluence_line(symbols: list[str]) -> str:
    """One compact line per full-confluence symbol, cache-only -- safe to
    call from chat context without ever blocking on network."""
    lines = []
    for sym in symbols:
        c = get_cached_confluence(sym)
        if not c or c.get("status") != "ok" or c["agreement"] != "full_confluence":
            continue
        lines.append(
            f"{sym}: {c['factor_count']} independent signals agree {c['direction']} "
            f"({', '.join(c['factors'].keys())})"
        )
    if not lines:
        return ""
    return "SIGNAL CONFLUENCE:\n" + "\n".join(f"  {l}" for l in lines)
