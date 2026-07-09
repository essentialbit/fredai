"""Wall Street analyst ratings + price-target consensus -- yfinance client.

Fills a documented gap: agent.py previously instructed Fred to never discuss
analyst ratings/price targets because this codebase had no data source for
them at all. yfinance.Ticker exposes real (not fabricated) upgrade/downgrade
history and consensus price-target stats for free, no API key -- same trust
boundary and same lazy/no-fast_info pattern as options_data_client.py.

Never touches Ticker.fast_info -- that reliably crashes this dev environment
(see standing memory note); nothing here needs it.
"""
import yfinance as yf


def fetch_analyst_snapshot(ticker: str) -> dict | None:
    """Recent upgrade/downgrade actions + consensus price-target stats for
    `ticker`. Returns None for tickers yfinance has no analyst coverage for
    (thinly-traded names, most ASX/crypto symbols, small caps) -- callers
    should treat that as "no data", not an error."""
    try:
        t = yf.Ticker(ticker)

        ratings = []
        ud = t.upgrades_downgrades
        if ud is not None and not ud.empty:
            recent = ud.sort_index(ascending=False).head(10)
            for graded_at, row in recent.iterrows():
                ratings.append({
                    "ticker": ticker,
                    "firm": row.get("Firm"),
                    "action": row.get("Action"),
                    "from_grade": row.get("FromGrade") or None,
                    "to_grade": row.get("ToGrade") or None,
                    "price_target": _clean_float(row.get("currentPriceTarget")),
                    "prior_price_target": _clean_float(row.get("priorPriceTarget")),
                    "graded_at": graded_at.strftime("%Y-%m-%d"),
                })

        consensus = None
        pt = t.analyst_price_targets
        if pt and pt.get("mean"):
            consensus = {
                "current": _clean_float(pt.get("current")),
                "high": _clean_float(pt.get("high")),
                "low": _clean_float(pt.get("low")),
                "mean": _clean_float(pt.get("mean")),
                "median": _clean_float(pt.get("median")),
            }

        if not ratings and not consensus:
            return None

        return {"ticker": ticker, "ratings": ratings, "consensus": consensus}
    except Exception as e:
        print(f"[AnalystData] fetch_analyst_snapshot({ticker}) failed: {e}")
        return None


def _clean_float(v) -> float | None:
    if v is None:
        return None
    try:
        v = float(v)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
