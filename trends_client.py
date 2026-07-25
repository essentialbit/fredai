"""Google Trends search-interest velocity via pytrends (unofficial, free, no API key).

Retail search-interest spikes for a ticker are a different, earlier-forming
signal than posted X/news sentiment -- search volume for "$TICKER crash" can
spike hours before news coverage catches up. pytrends is an unofficial
reverse-engineered wrapper known to intermittently 429 under sustained load,
so every call here quietly skips-and-logs on failure exactly like the
existing Reddit RSS / Finviz feeds -- never a hard dependency.
"""
import time

from memory_store import insert_trends_interest

_KEYWORD_SUFFIX = " stock"


def fetch_search_interest(ticker: str) -> float | None:
    """Latest complete-hour Google Trends interest-over-time score (0-100)
    for '<ticker> stock' over the trailing 7 days. Returns None on any
    failure (rate-limited, delisted/unrecognized ticker, pytrends layout
    change, etc.) or if the only available row is the current in-progress
    hour (isPartial)."""
    try:
        from pytrends.request import TrendReq
        keyword = f"{ticker}{_KEYWORD_SUFFIX}"
        pytrends = TrendReq(hl="en-US", tz=0)
        pytrends.build_payload([keyword], timeframe="now 7-d")
        df = pytrends.interest_over_time()
        if df is None or df.empty or keyword not in df.columns:
            return None
        if "isPartial" in df.columns:
            df = df[df["isPartial"] == False]  # noqa: E712 -- pandas boolean column, not a Python bool
        if df.empty:
            return None
        return float(df[keyword].iloc[-1])
    except Exception as e:
        print(f"[GoogleTrends] fetch_search_interest({ticker}) failed: {e}")
        return None


def refresh_trends_interest(tickers: list[str], delay_s: float = 2.0) -> int:
    """Fetch and store one daily snapshot per ticker. Returns count stored."""
    stored = 0
    for i, sym in enumerate(tickers):
        score = fetch_search_interest(sym)
        if score is not None:
            insert_trends_interest(sym, f"{sym}{_KEYWORD_SUFFIX}", score)
            stored += 1
        if i < len(tickers) - 1:
            time.sleep(delay_s)
    return stored
