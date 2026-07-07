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
    get_news, get_recent_insider_transactions, get_short_interest_direction,
)
from technical_alerts import get_technicals

CHECKPOINTS = (("4h", 4), ("24h", 24), ("72h", 72))


def _direction(avg_sentiment: float) -> str:
    if avg_sentiment > 0.05:
        return "bullish"
    if avg_sentiment < -0.05:
        return "bearish"
    return "neutral"


def _baseline_direction(quote: dict | None) -> str | None:
    """Naive momentum benchmark: same direction as the prior move (previous
    close -> now). A source only proves its worth if it beats this."""
    if not quote or quote.get("change_pct") is None:
        return None
    chg = quote["change_pct"]
    if chg > 0:
        return "bullish"
    if chg < 0:
        return "bearish"
    return "neutral"


def _news_sentiment_direction(asset: str) -> tuple[str, float, int] | None:
    """Independent of the aggregate/fallback blend used for the primary
    prediction -- reads news_items directly so this source can be measured
    on its own, even once real X signals return and 'aggregate' becomes a
    mix of both."""
    items = get_news(ticker=asset, hours=4, limit=50)
    scores = [n["sentiment_score"] for n in items if n.get("sentiment_score") is not None]
    if not scores:
        return None
    avg = sum(scores) / len(scores)
    return _direction(avg), avg, len(scores)


# get_recent_insider_transactions' signal_type is the transaction-code name
# (SIGNAL_CODES in sec_client.py: "open_market_purchase"/"open_market_sale"),
# not a bullish/bearish label -- map it to a direction here rather than
# assuming it already is one (caught by the functional test against real
# live Form 4 data, which surfaced a real "sale" mislabeled as a raw string).
_INSIDER_DIRECTION = {"open_market_purchase": "bullish", "open_market_sale": "bearish"}


def _insider_direction(asset: str) -> str | None:
    txns = get_recent_insider_transactions(asset, days=90, signal_only=True)
    if not txns:
        return None
    return _INSIDER_DIRECTION.get(txns[0].get("signal_type"))


def _technical_direction(asset: str) -> str | None:
    t = get_technicals(asset)
    sma20, sma50 = t.get("sma20"), t.get("sma50")
    if sma20 is None or sma50 is None or sma20 == sma50:
        return None
    return "bullish" if sma20 > sma50 else "bearish"


def log_scan_outcomes(trending: list[dict], quotes: dict, limit: int = 10):
    """Called once per scan cycle (job_scan_cycle) with the same `trending`
    (get_trending_assets()) and `quotes` (already-fetched, no new yfinance
    calls here) the cycle already has on hand.

    Logs the existing blended 'aggregate' row unchanged, plus one row per
    independent source that actually has data for this asset right now --
    per-source rows are skipped rather than fabricated when a source is
    silent (no insider filing, no short-interest trend, etc), per
    MISSION.md Principle #7. Insider/short-interest/technical reads are
    DB-local (already populated by their own scheduled jobs) -- no new
    external fetches added here."""
    for row in trending[:limit]:
        asset = row.get("asset")
        if not asset:
            continue
        quote = quotes.get(asset)
        price = (quote or {}).get("price")
        baseline = _baseline_direction(quote)

        log_signal_outcome(
            asset=asset,
            predicted_direction=_direction(row.get("avg_sentiment") or 0.0),
            signal_count=row.get("signal_count", 0),
            avg_sentiment=row.get("avg_sentiment"),
            price_at_t0=price,
            source="aggregate",
            baseline_direction=baseline,
        )

        news = _news_sentiment_direction(asset)
        if news:
            direction, avg_sentiment, count = news
            log_signal_outcome(
                asset=asset, predicted_direction=direction, signal_count=count,
                avg_sentiment=avg_sentiment, price_at_t0=price,
                source="news_sentiment", baseline_direction=baseline,
            )

        insider = _insider_direction(asset)
        if insider:
            log_signal_outcome(
                asset=asset, predicted_direction=insider, signal_count=1,
                avg_sentiment=None, price_at_t0=price,
                source="insider", baseline_direction=baseline,
            )

        short_dir = get_short_interest_direction(asset)
        if short_dir:
            log_signal_outcome(
                asset=asset, predicted_direction=short_dir, signal_count=1,
                avg_sentiment=None, price_at_t0=price,
                source="short_interest", baseline_direction=baseline,
            )

        technical = _technical_direction(asset)
        if technical:
            log_signal_outcome(
                asset=asset, predicted_direction=technical, signal_count=1,
                avg_sentiment=None, price_at_t0=price,
                source="technical", baseline_direction=baseline,
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
    """Accuracy per checkpoint over the last 30 days, broken down per source
    with a naive-baseline delta -- the v2 shape MISSION.md Principle #4
    actually needs to be enforceable (a source only "proves value" if it
    beats doing nothing clever, not just if its raw hit rate looks high)."""
    return {label: get_backtest_accuracy(label, hours=24 * 30) for label, _ in CHECKPOINTS}


def get_underperforming_sources(min_sample: int = 20) -> list[dict]:
    """Sources with a 30-day baseline delta <= 0 at any checkpoint, sample
    size large enough to mean something. Flags only -- a human decides
    removal, this never deletes a source itself."""
    flagged = []
    for label, _ in CHECKPOINTS:
        report = get_backtest_accuracy(label, hours=24 * 30)
        for source, stats in report.get("sources", {}).items():
            if source == "aggregate":
                continue
            if stats.get("proving_value") is False and stats.get("total", 0) >= min_sample:
                flagged.append({
                    "source": source, "checkpoint": label,
                    "accuracy_pct": stats["accuracy_pct"],
                    "baseline_accuracy_pct": stats["baseline_accuracy_pct"],
                    "baseline_delta_pct": stats["baseline_delta_pct"],
                    "sample": stats["total"],
                })
    return flagged
