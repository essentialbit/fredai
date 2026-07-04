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
    # ── US Markets ──────────────────────────────────────────────────────────
    {"url": "https://finance.yahoo.com/news/rssindex", "source": "Yahoo Finance", "category": "market"},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/", "source": "MarketWatch", "category": "market"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "source": "CNBC", "category": "market"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "source": "Bloomberg", "category": "market"},
    {"url": "https://www.investing.com/rss/news_301.rss", "source": "Investing.com", "category": "market"},
    {"url": "https://seekingalpha.com/market_currents.xml", "source": "Seeking Alpha", "category": "market"},
    {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "source": "WSJ Markets", "category": "market"},
    {"url": "https://www.ft.com/rss/home", "source": "Financial Times", "category": "market"},
    # ── Central banks & macro policy ────────────────────────────────────────
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "source": "Federal Reserve", "category": "central_bank"},
    {"url": "https://www.ecb.europa.eu/rss/press.html", "source": "ECB", "category": "central_bank"},
    {"url": "https://www.bankofengland.co.uk/rss/news", "source": "Bank of England", "category": "central_bank"},
    {"url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "source": "CNBC Economy", "category": "macro"},
    # IMF's own RSS endpoints all 302/307-redirect without ever resolving to
    # parseable XML (verified with feedparser directly) -- Google News' own
    # site-scoped search RSS is a reliable, real substitute for "recent IMF
    # coverage" without needing to reverse-engineer whatever replaced it.
    {"url": "https://news.google.com/rss/search?q=site:imf.org+when:7d&hl=en-US&gl=US&ceid=US:en", "source": "IMF", "category": "macro"},
    # ── Global Geopolitics ───────────────────────────────────────────────────
    # feeds.reuters.com was retired -- Reuters no longer serves a public RSS
    # feed for this at all (every current candidate URL 401s or times out).
    # Google News' World-topic feed reliably includes Reuters/AP wire content.
    {"url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en", "source": "Global Wire (AP/Reuters)", "category": "geopolitical"},
    {"url": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "source": "CNBC Politics", "category": "geopolitical"},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "source": "BBC Business", "category": "geopolitical"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "source": "Al Jazeera", "category": "geopolitical"},
    {"url": "https://www3.nhk.or.jp/rss/news/cat6.xml", "source": "NHK Asia", "category": "geopolitical"},
    # ── Asia-Pacific ─────────────────────────────────────────────────────────
    {"url": "https://asia.nikkei.com/rss/feed/nar", "source": "Nikkei Asia", "category": "market"},
    {"url": "https://www.scmp.com/rss/91/feed", "source": "SCMP Business", "category": "market"},
    # AFR's RSS was retired (404 on every path checked) -- not replaced: this
    # is Australia-specific and asx_client.py's dedicated AU coverage already
    # exists, so losing this doesn't reduce genuine global signal.
    # ── AI & Tech (global) ───────────────────────────────────────────────────
    {"url": "https://feeds.feedburner.com/venturebeat/SZYF", "source": "VentureBeat AI", "category": "ai"},
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "source": "TechCrunch AI", "category": "ai"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "source": "The Verge AI", "category": "ai"},
    {"url": "https://www.cnbc.com/id/19854910/device/rss/rss.html", "source": "CNBC Tech", "category": "ai"},
    {"url": "https://www.wired.com/feed/category/business/latest/rss", "source": "Wired Business", "category": "ai"},
]

# Geographic coordinates for globe visualization: source → (lat, lng, region_label)
SOURCE_COORDINATES: dict[str, tuple[float, float, str]] = {
    "Yahoo Finance":     (40.71, -74.00, "New York, USA"),
    "MarketWatch":       (40.71, -74.00, "New York, USA"),
    "CNBC":              (40.71, -74.01, "New York, USA"),
    "Bloomberg":         (40.75, -73.99, "New York, USA"),
    "Investing.com":     (32.06, 34.77,  "Tel Aviv, Israel"),
    "Seeking Alpha":     (37.77, -122.42,"San Francisco, USA"),
    "WSJ Markets":       (40.71, -74.00, "New York, USA"),
    "Financial Times":   (51.50, -0.12,  "London, UK"),
    "Federal Reserve":   (38.89, -77.04, "Washington D.C., USA"),
    "ECB":               (50.11, 8.68,   "Frankfurt, Germany"),
    "Bank of England":   (51.51, -0.09,  "London, UK"),
    "CNBC Economy":      (40.71, -74.01, "New York, USA"),
    "IMF":               (38.89, -77.04, "Washington D.C., USA"),
    "Global Wire (AP/Reuters)": (51.50, -0.12, "London, UK"),
    "CNBC Politics":     (38.89, -77.04, "Washington D.C., USA"),
    "BBC Business":      (51.51, -0.13,  "London, UK"),
    "Al Jazeera":        (25.28, 51.52,  "Doha, Qatar"),
    "NHK Asia":          (35.68, 139.76, "Tokyo, Japan"),
    "Nikkei Asia":       (35.68, 139.76, "Tokyo, Japan"),
    "SCMP Business":     (22.32, 114.17, "Hong Kong"),
    "VentureBeat AI":    (37.77, -122.42,"San Francisco, USA"),
    "TechCrunch AI":     (37.77, -122.42,"San Francisco, USA"),
    "The Verge AI":      (40.71, -74.00, "New York, USA"),
    "CNBC Tech":         (37.77, -122.42,"San Francisco, USA"),
    "Wired Business":    (37.77, -122.42,"San Francisco, USA"),
}

_FINANCIAL_KEYWORDS = re.compile(
    r'\b(stock|market|invest|trade|earn|revenue|profit|loss|GDP|inflation|rate|bond|'
    r'fed|fomc|rba|reserve bank|tariff|sanction|geopolit|war|conflict|supply chain|'
    r'semiconductor|AI|nvidia|apple|tesla|crypto|bitcoin|ethereum)\b',
    re.IGNORECASE
)

_TICKER_MENTION = re.compile(r'\b([A-Z]{2,5})(?:\s*-\s*USD)?\b|\$([A-Z]{2,5})\b')


def translate_to_english(text: str) -> tuple[str, bool]:
    """
    Translates non-English text to English using Google's public translation endpoint.
    Returns: (translated_text, was_translated)
    """
    if not text or not text.strip():
        return text, False
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "en",
            "dt": "t",
            "q": text
        }
        r = requests.get(url, params=params, headers=_HEADERS, timeout=6)
        if r.status_code == 200:
            res = r.json()
            if res and res[0]:
                translated = "".join([part[0] for part in res[0] if part[0]])
                detected_lang = res[2]
                was_translated = (detected_lang != "en")
                return translated, was_translated
    except Exception as e:
        print(f"[Translate] Failed: {e}")
    return text, False


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


def _score(title: str, summary: str) -> tuple[float, str]:
    text = f"{title} {summary}"[:500]
    try:
        from finbert_sentiment import analyze_sentiment
        res = analyze_sentiment(text)
        if res is not None:
            score, stype = res
            return round(score, 3), "finbert"
    except Exception as e:
        print(f"[News Client] FinBERT scoring error: {e}")

    return round(_vader.polarity_scores(text)["compound"], 3), "vader"


def _extract_tickers(text: str, watchlist: list[str]) -> str:
    found = set()
    for m in _TICKER_MENTION.finditer(text):
        sym = m.group(1) or m.group(2)
        if sym and sym in watchlist:
            found.add(sym)

    if not found:
        # News prose routinely names a company without ever using its raw
        # ticker or a cashtag ("Apple reported strong earnings") -- NER-based
        # linking catches that. No-op if spaCy/the model isn't available.
        try:
            from signal_processor import extract_and_link_tickers
            found.update(extract_and_link_tickers(text))
        except Exception:
            pass

    return ",".join(sorted(found))


def _parse_feed(feed_meta: dict, watchlist: list[str]) -> list[dict]:
    items = []
    try:
        f = feedparser.parse(feed_meta["url"])
        for entry in f.entries[:30]:
            title = (entry.get("title") or "").strip()
            summary = BeautifulSoup(entry.get("summary") or "", "html.parser").get_text()[:500].strip()

            # Auto-translate if non-English
            trans_title, is_title_trans = translate_to_english(title)
            trans_summary, is_summary_trans = translate_to_english(summary)
            if is_title_trans or is_summary_trans:
                title = f"[Translated] {trans_title}"
                summary = trans_summary

            url = entry.get("link") or ""
            guid = entry.get("id") or _guid(url, title)

            text = f"{title} {summary}"
            tickers = _extract_tickers(text, watchlist)
            score, model = _score(title, summary)

            items.append({
                "guid": guid,
                "title": title,
                "summary": summary,
                "url": url,
                "source": feed_meta["source"],
                "category": feed_meta["category"],
                "tickers": tickers,
                "sentiment_score": score,
                "sentiment_model": model,
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

                # Auto-translate if non-English
                trans_title, is_title_trans = translate_to_english(title)
                trans_summary, is_summary_trans = translate_to_english(summary)
                if is_title_trans or is_summary_trans:
                    title = f"[Translated] {trans_title}"
                    summary = trans_summary

                url = entry.get("link") or ""
                guid = entry.get("id") or _guid(url, title)
                score, model = _score(title, summary)
                items.append({
                    "guid": guid,
                    "title": title,
                    "summary": summary.strip(),
                    "url": url,
                    "source": "Yahoo Finance",
                    "category": "ticker",
                    "tickers": sym,
                    "sentiment_score": score,
                    "sentiment_model": model,
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
