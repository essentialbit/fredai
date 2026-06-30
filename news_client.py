"""News aggregator — RSS multi-source scraper with VADER sentiment scoring.

Sources:
  Ticker-scoped  : Yahoo Finance per-symbol RSS
  Market/macro   : CNBC, MarketWatch, Bloomberg, Yahoo Finance top, Investing.com
  Central banks  : Federal Reserve press releases, RBA (scraped)
  AI sector      : Dedicated AI/tech news feeds
  Geopolitical   : Reuters world news
"""
import hashlib
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from memory_store import upsert_news_items, upsert_ticker_info

_vader = SentimentIntensityAnalyzer()
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── FEED REGISTRY ─────────────────────────────────────────────────────────────

MACRO_FEEDS = [
    # Market & finance
    {"url": "https://finance.yahoo.com/news/rssindex", "source": "Yahoo Finance", "category": "market"},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/", "source": "MarketWatch", "category": "market"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "source": "CNBC", "category": "market"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "source": "Bloomberg", "category": "market"},
    {"url": "https://www.investing.com/rss/news_301.rss", "source": "Investing.com", "category": "market"},
    {"url": "https://seekingalpha.com/market_currents.xml", "source": "Seeking Alpha", "category": "market"},
    # Central banks & macro policy
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "source": "Federal Reserve", "category": "central_bank"},
    {"url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "source": "CNBC Economy", "category": "macro"},
    # Geopolitics
    {"url": "https://feeds.reuters.com/reuters/worldNews", "source": "Reuters World", "category": "geopolitical"},
    {"url": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "source": "CNBC Politics", "category": "geopolitical"},
    # AI & Tech
    {"url": "https://feeds.feedburner.com/venturebeat/SZYF", "source": "VentureBeat AI", "category": "ai"},
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "source": "TechCrunch AI", "category": "ai"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "source": "The Verge AI", "category": "ai"},
    {"url": "https://www.cnbc.com/id/100084241/device/rss/rss.html", "source": "CNBC Tech", "category": "ai"},
    # Australian / RBA
    {"url": "https://www.afr.com/rss", "source": "AFR", "category": "australia"},
]

_FINANCIAL_KEYWORDS = re.compile(
    r'\b(stock|market|invest|trade|earn|revenue|profit|loss|GDP|inflation|rate|bond|'
    r'fed|fomc|rba|reserve bank|tariff|sanction|geopolit|war|conflict|supply chain|'
    r'semiconductor|AI|nvidia|apple|tesla|crypto|bitcoin|ethereum)\b',
    re.IGNORECASE
)

_TICKER_MENTION = re.compile(r'\b([A-Z]{2,5})(?:\s*-\s*USD)?\b|\$([A-Z]{2,5})\b')


def _guid(url: str, title: str) -> str:
    return hashlib.md5(f"{url}{title}".encode()).hexdigest()


def _parse_date(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = datetime(*val[:6], tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
    try:
        raw = getattr(entry, "published", "") or getattr(entry, "updated", "")
        if raw:
            return parsedate_to_datetime(raw).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _score(title: str, summary: str) -> float:
    text = f"{title} {summary}"[:500]
    return round(_vader.polarity_scores(text)["compound"], 3)


def _extract_tickers(text: str, watchlist: list[str]) -> str:
    found = set()
    for m in _TICKER_MENTION.finditer(text):
        sym = m.group(1) or m.group(2)
        if sym and sym in watchlist:
            found.add(sym)
    return ",".join(sorted(found))


def _parse_feed(feed_meta: dict, watchlist: list[str]) -> list[dict]:
    items = []
    try:
        f = feedparser.parse(feed_meta["url"])
        for entry in f.entries[:30]:
            title = (entry.get("title") or "").strip()
            summary = BeautifulSoup(entry.get("summary") or "", "html.parser").get_text()[:500].strip()
            url = entry.get("link") or ""
            guid = entry.get("id") or _guid(url, title)

            text = f"{title} {summary}"
            tickers = _extract_tickers(text, watchlist)
            score = _score(title, summary)

            items.append({
                "guid": guid,
                "title": title,
                "summary": summary,
                "url": url,
                "source": feed_meta["source"],
                "category": feed_meta["category"],
                "tickers": tickers,
                "sentiment_score": score,
                "published_at": _parse_date(entry),
            })
    except Exception as e:
        print(f"[News] Feed error {feed_meta['source']}: {e}")
    return items


def _fetch_rba_news() -> list[dict]:
    """RBA doesn't serve a parseable RSS — scrape HTML news page."""
    items = []
    try:
        r = requests.get("https://www.rba.gov.au/news/", headers=_HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for article in soup.select("div.item, li.article")[:15]:
            title_el = article.find(["h2", "h3", "a"])
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link_el = article.find("a")
            url = ("https://www.rba.gov.au" + link_el["href"]) if link_el and link_el.get("href","").startswith("/") else ""
            date_el = article.find(["time", "span"], class_=re.compile("date|time", re.I))
            pub = date_el.get_text(strip=True) if date_el else ""
            items.append({
                "guid": _guid(url, title),
                "title": title,
                "summary": "Reserve Bank of Australia official announcement.",
                "url": url,
                "source": "RBA",
                "category": "central_bank",
                "tickers": "",
                "sentiment_score": 0.0,
                "published_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            })
    except Exception as e:
        print(f"[News] RBA scrape error: {e}")
    return items


def _fetch_per_ticker(symbols: list[str]) -> list[dict]:
    """Yahoo Finance per-ticker RSS — one request per symbol with stagger."""
    items = []
    for sym in symbols[:15]:
        try:
            time.sleep(0.3)
            f = feedparser.parse(f"https://finance.yahoo.com/rss/headline?s={sym}")
            for entry in f.entries[:8]:
                title = (entry.get("title") or "").strip()
                summary = BeautifulSoup(entry.get("summary") or "", "html.parser").get_text()[:400]
                url = entry.get("link") or ""
                guid = entry.get("id") or _guid(url, title)
                items.append({
                    "guid": guid,
                    "title": title,
                    "summary": summary.strip(),
                    "url": url,
                    "source": "Yahoo Finance",
                    "category": "ticker",
                    "tickers": sym,
                    "sentiment_score": _score(title, summary),
                    "published_at": _parse_date(entry),
                })
        except Exception:
            pass
    return items


def fetch_all_news(watchlist: list[str]) -> int:
    """Fetch and store all news. Returns count of new items saved."""
    all_items = []

    # Per-ticker Yahoo Finance
    all_items.extend(_fetch_per_ticker(watchlist))

    # Macro/market/geopolitical/AI feeds
    for feed_meta in MACRO_FEEDS:
        all_items.extend(_parse_feed(feed_meta, watchlist))
        time.sleep(0.2)

    # RBA
    all_items.extend(_fetch_rba_news())

    return upsert_news_items(all_items)


# ── TICKER INFO ENRICHMENT ────────────────────────────────────────────────────

_INFO_BASE = "https://query1.finance.yahoo.com"


def fetch_ticker_info(symbol: str) -> dict | None:
    try:
        r = requests.get(
            f"{_INFO_BASE}/v8/finance/chart/{symbol}?interval=1d&range=1d",
            headers=_HEADERS, timeout=12
        )
        if r.status_code != 200:
            return None
        result = r.json().get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        name = meta.get("longName") or meta.get("shortName") or symbol
        info = {
            "symbol": symbol,
            "name": name,
            "sector": None,
            "industry": None,
            "description": None,
            "country": meta.get("exchangeTimezoneName", "").split("/")[0] if "/" in meta.get("exchangeTimezoneName", "") else None,
            "market_cap": meta.get("marketCap"),
        }
        upsert_ticker_info(info)
        return info
    except Exception as e:
        print(f"[News] Ticker info failed for {symbol}: {e}")
        return None
