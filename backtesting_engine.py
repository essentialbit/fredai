"""
FredAI Backtesting Engine (FSI L3)
=====================================
Tracks whether Fred's own aggregated per-asset signal direction (from each
scan cycle's get_trending_assets() snapshot) actually predicted the right
price movement, at 4h/24h/72h checkpoints. Foundational L3 capability —
lets Fred (and the collaboration board) measure whether a given signal
source is actually predictive, rather than assuming it.

Deliberately tracks one outcome row per asset per scan cycle (not one per
raw signal) — this codebase already needs dedicated rate-limit resilience
for yfinance's regular quote endpoints, so multiplying price lookups by
tracking every individual tweet/news item would make that worse for no
real backtesting benefit (many signals for the same asset in one 4h
window are the same prediction, not independent ones).
"""
from market_data import fetch_quotes
from memory_store import (
    log_signal_outcome, get_pending_outcomes, update_outcome_price, get_backtest_accuracy,
)

CHECKPOINTS = (("4h", 4), ("24h", 24), ("72h", 72))


def _direction(avg_sentiment: float) -> str:
    if avg_sentiment > 0.05:
        return "bullish"
    if avg_sentiment < -0.05:
        return "bearish"
    return "neutral"


def log_scan_outcomes(trending: list[dict], quotes: dict, limit: int = 10):
    """Called once per scan cycle (job_scan_cycle) with the same `trending`
    (get_trending_assets()) and `quotes` (already-fetched, no new yfinance
    calls here) the cycle already has on hand."""
    for row in trending[:limit]:
        asset = row.get("asset")
        if not asset:
            continue
        price = (quotes.get(asset) or {}).get("price")
        log_signal_outcome(
            asset=asset,
            predicted_direction=_direction(row.get("avg_sentiment") or 0.0),
            signal_count=row.get("signal_count", 0),
            avg_sentiment=row.get("avg_sentiment"),
            price_at_t0=price,
        )


def run_backtest_check() -> dict:
    """Scheduled job: for each checkpoint whose time has come, fetch the
    current price for any still-pending outcome and record it."""
    filled = 0
    errors = 0
    for label, hours in CHECKPOINTS:
        pending = get_pending_outcomes(label, min_hours=hours)
        if not pending:
            continue
        assets = list({p["asset"] for p in pending})
        prices = fetch_quotes(assets)
        for row in pending:
            price = (prices.get(row["asset"]) or {}).get("price")
            if price is None:
                errors += 1
                continue
            update_outcome_price(row["id"], label, price)
            filled += 1
    return {"filled": filled, "errors": errors}


def get_accuracy_report() -> dict:
    """Basic reporting function per the proposal spec — accuracy at each
    checkpoint over the last 30 days."""
    return {label: get_backtest_accuracy(label, hours=24 * 30) for label, _ in CHECKPOINTS}
