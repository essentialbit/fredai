"""Analyst rating / price-target data client (FSI L2).

Fred previously had zero analyst-rating data and was explicitly instructed
to never invent one (agent.py's "no analyst-rating data source at all"
caveat). yfinance.Ticker exposes three real, populated properties for
liquid tickers -- upgrades_downgrades, analyst_price_targets,
recommendations -- live-verified this cycle (AAPL: 969 real upgrade/
downgrade rows spanning years, a real consensus target, real trailing
buy/hold/sell counts, exit 0/no crash).

Deliberately never touches yfinance.Ticker.fast_info or .history() -- both
reliably crash this dev environment's pandas path (see project memory).
These three analyst-data properties are separate code paths and were
live-verified clean.
"""
import time

import yfinance as yf

from memory_store import insert_analyst_ratings, get_recent_analyst_ratings

_CACHE_TTL_S = 3600  # analyst actions are sparse/daily at most; hourly is plenty
_cache: dict = {}


def refresh_analyst_ratings(ticker: str) -> int:
    """Fetch recent upgrades/downgrades from yfinance and persist new rows.
    Returns count of newly-inserted rows -- 0 (never raises) if the ticker
    has no coverage or the fetch fails, matching every other market-data
    client's graceful-degradation convention."""
    try:
        df = yf.Ticker(ticker).upgrades_downgrades
    except Exception as e:
        print(f"[AnalystData] upgrades_downgrades failed for {ticker}: {e}")
        return 0
    if df is None or df.empty:
        return 0

    rows = []
    for graded_at, row in df.head(20).iterrows():
        rows.append({
            "ticker": ticker,
            "firm": row.get("Firm"),
            "action": row.get("Action"),
            "from_grade": row.get("FromGrade"),
            "to_grade": row.get("ToGrade"),
            "price_target": float(row["currentPriceTarget"]) if row.get("currentPriceTarget") else None,
            "prior_price_target": float(row["priorPriceTarget"]) if row.get("priorPriceTarget") else None,
            "graded_at": graded_at.strftime("%Y-%m-%d") if hasattr(graded_at, "strftime") else str(graded_at),
        })
    return insert_analyst_ratings(rows)


def get_price_target_consensus(ticker: str, force: bool = False) -> dict | None:
    """{"current", "high", "low", "mean", "median", "upside_pct"} from
    yfinance's live consensus snapshot, TTL-cached. None if unavailable
    (falls back to the last good cached read on a transient fetch error)."""
    now = time.time()
    cached = _cache.get(ticker)
    if not force and cached and now - cached["computed_at"] < _CACHE_TTL_S:
        return cached["data"]
    try:
        pt = yf.Ticker(ticker).analyst_price_targets
    except Exception as e:
        print(f"[AnalystData] analyst_price_targets failed for {ticker}: {e}")
        return cached["data"] if cached else None
    if not pt:
        return cached["data"] if cached else None

    data = {
        "current": pt.get("current"),
        "high": pt.get("high"),
        "low": pt.get("low"),
        "mean": pt.get("mean"),
        "median": pt.get("median"),
    }
    if data["current"] and data["mean"]:
        data["upside_pct"] = round((data["mean"] - data["current"]) / data["current"] * 100, 2)
    _cache[ticker] = {"computed_at": now, "data": data}
    return data


def get_recommendation_trend(ticker: str) -> dict | None:
    """Most recent month's trailing strong_buy/buy/hold/sell/strong_sell
    counts, or None if unavailable."""
    try:
        rec = yf.Ticker(ticker).recommendations
    except Exception as e:
        print(f"[AnalystData] recommendations failed for {ticker}: {e}")
        return None
    if rec is None or rec.empty:
        return None
    latest = rec.iloc[0]
    return {
        "strong_buy": int(latest.get("strongBuy", 0) or 0),
        "buy": int(latest.get("buy", 0) or 0),
        "hold": int(latest.get("hold", 0) or 0),
        "sell": int(latest.get("sell", 0) or 0),
        "strong_sell": int(latest.get("strongSell", 0) or 0),
    }


def get_analyst_summary(ticker: str) -> dict | None:
    """Combined view for report/context injection: consensus target +
    most recent stored rating actions. None if neither source has data --
    callers must not fabricate a summary when this returns None."""
    ticker = ticker.upper()
    consensus = get_price_target_consensus(ticker)
    recent = get_recent_analyst_ratings(ticker, days=180, limit=5)
    if not consensus and not recent:
        return None
    return {"consensus": consensus, "recent_actions": recent}
