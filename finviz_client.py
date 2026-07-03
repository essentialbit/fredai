"""Finviz short-interest scraper — short float % and short ratio (days-to-cover).

Structural market context for detecting short-squeeze setups. Free (no API key,
no rate-limit auth) — polite scraping with a real browser User-Agent, one
request per ticker, no concurrency.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from memory_store import insert_short_interest

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
_QUOTE_URL = "https://finviz.com/quote.ashx?t={symbol}"


def _parse_pct(text: str) -> float | None:
    m = re.search(r"([\d.]+)%", text or "")
    return float(m.group(1)) if m else None


def _parse_float(text: str) -> float | None:
    m = re.search(r"[\d.]+", text or "")
    return float(m.group(0)) if m else None


def fetch_short_interest(ticker: str) -> dict | None:
    """Scrape Short Float % and Short Ratio (days-to-cover) for a US-listed ticker.

    Returns {"symbol", "short_float_pct", "short_ratio"} or None if the page
    didn't return the expected snapshot table (delisted/invalid ticker, or
    Finviz layout changed).
    """
    try:
        r = requests.get(_QUOTE_URL.format(symbol=ticker), headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        short_float_pct = None
        short_ratio = None
        for label_div in soup.select("td.snapshot-td2 div.snapshot-td-label"):
            label = label_div.get_text(strip=True)
            if label not in ("Short Float", "Short Ratio"):
                continue
            value_td = label_div.find_parent("td").find_next_sibling("td")
            if value_td is None:
                continue
            value_text = value_td.get_text(strip=True)
            if label == "Short Float":
                short_float_pct = _parse_pct(value_text)
            elif label == "Short Ratio":
                short_ratio = _parse_float(value_text)

        if short_float_pct is None and short_ratio is None:
            return None

        return {"symbol": ticker, "short_float_pct": short_float_pct, "short_ratio": short_ratio}
    except Exception as e:
        print(f"[Finviz] fetch_short_interest({ticker}) failed: {e}")
        return None


def refresh_short_interest(tickers: list[str], delay_s: float = 1.0) -> int:
    """Fetch and store a daily snapshot for each ticker. Returns count stored."""
    stored = 0
    for i, sym in enumerate(tickers):
        data = fetch_short_interest(sym)
        if data:
            insert_short_interest(sym, data["short_float_pct"], data["short_ratio"])
            stored += 1
        if i < len(tickers) - 1:
            time.sleep(delay_s)
    return stored
