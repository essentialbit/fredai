"""
ASX Data Client — Australian Securities Exchange integration.

Data sources (all public, no auth required):
  - Yahoo Finance v8 API with .AX suffix  → quotes, history, company metadata
  - Yahoo Finance search API              → ticker news
  - SMH Business RSS                      → Australian financial news
  - Stockhead RSS                         → ASX-focused market news
  - Yahoo Finance AU RSS                  → AU market news
  - Seeking Alpha AU                      → ASX company analysis

Note: api.asxonline.com/mia is a gated ASX-participant API requiring ASX Online
account + MFA. The Bloomberg BLPAPI requires a Terminal subscription. This
client uses the publicly accessible data layer instead.
"""
import time
import requests
import feedparser
from datetime import datetime
from news_client import _is_financially_relevant

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_YF_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
_YF_CHART2 = "https://query2.finance.yahoo.com/v8/finance/chart"
_YF_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"

# ── ASX BLUE CHIPS ────────────────────────────────────────────────────────────
ASX_TICKERS = {
    # Big 4 Banks
    "CBA.AX": "Commonwealth Bank", "WBC.AX": "Westpac", "ANZ.AX": "ANZ",
    "NAB.AX": "NAB",
    # Mining & Resources
    "BHP.AX": "BHP Group", "RIO.AX": "Rio Tinto", "FMG.AX": "Fortescue",
    "S32.AX": "South32", "MIN.AX": "Mineral Resources", "LYC.AX": "Lynas Rare Earths",
    "PLS.AX": "Pilbara Minerals", "IGO.AX": "IGO",
    # Energy
    "WDS.AX": "Woodside Energy", "STO.AX": "Santos", "VEA.AX": "Viva Energy",
    # Healthcare & Biotech
    "CSL.AX": "CSL Limited", "COH.AX": "Cochlear", "RMD.AX": "ResMed",
    "SHL.AX": "Sonic Healthcare", "PME.AX": "Pro Medicus",
    # Tech & Software
    "WTC.AX": "WiseTech Global", "XRO.AX": "Xero", "SEK.AX": "SEEK",
    "REA.AX": "REA Group", "CAR.AX": "CAR Group", "CPU.AX": "Computershare",
    "TLX.AX": "Telix Pharmaceuticals",
    # Retail & Consumer
    "WES.AX": "Wesfarmers", "WOW.AX": "Woolworths", "COL.AX": "Coles",
    "JBH.AX": "JB Hi-Fi",
    # Finance & Insurance
    "MQG.AX": "Macquarie Group", "IAG.AX": "Insurance Australia",
    "QBE.AX": "QBE Insurance", "SUN.AX": "Suncorp",
    # Industrials & Infrastructure
    "TCL.AX": "Transurban", "SYD.AX": "Sydney Airport",
    "AMC.AX": "Amcor", "APA.AX": "APA Group",
    # Index ETFs
    "VAS.AX": "Vanguard ASX 300 ETF", "IOZ.AX": "iShares ASX 200 ETF",
    "NDQ.AX": "BetaShares Nasdaq 100 ETF",
}

ASX_SECTORS = {
    "CBA.AX": "ASX Banks", "WBC.AX": "ASX Banks", "ANZ.AX": "ASX Banks", "NAB.AX": "ASX Banks",
    "BHP.AX": "ASX Mining", "RIO.AX": "ASX Mining", "FMG.AX": "ASX Mining",
    "S32.AX": "ASX Mining", "MIN.AX": "ASX Mining", "LYC.AX": "ASX Mining",
    "PLS.AX": "ASX Mining", "IGO.AX": "ASX Mining",
    "WDS.AX": "ASX Energy", "STO.AX": "ASX Energy", "VEA.AX": "ASX Energy",
    "CSL.AX": "ASX Healthcare", "COH.AX": "ASX Healthcare", "RMD.AX": "ASX Healthcare",
    "SHL.AX": "ASX Healthcare", "PME.AX": "ASX Healthcare",
    "WTC.AX": "ASX Tech", "XRO.AX": "ASX Tech", "SEK.AX": "ASX Tech",
    "REA.AX": "ASX Tech", "CAR.AX": "ASX Tech", "CPU.AX": "ASX Tech",
    "TLX.AX": "ASX Healthcare",
    "WES.AX": "ASX Retail", "WOW.AX": "ASX Retail", "COL.AX": "ASX Retail",
    "JBH.AX": "ASX Retail",
    "MQG.AX": "ASX Finance", "IAG.AX": "ASX Finance",
    "QBE.AX": "ASX Finance", "SUN.AX": "ASX Finance",
    "TCL.AX": "ASX Infrastructure", "SYD.AX": "ASX Infrastructure",
    "AMC.AX": "ASX Industrials", "APA.AX": "ASX Infrastructure",
    "VAS.AX": "ASX ETF", "IOZ.AX": "ASX ETF", "NDQ.AX": "ASX ETF",
}

ASX_SECTOR_COLORS = {
    "ASX Banks":          "#00b4ff",
    "ASX Mining":         "#f5a623",
    "ASX Energy":         "#ff3b5c",
    "ASX Healthcare":     "#ff6b9d",
    "ASX Tech":           "#00ff88",
    "ASX Retail":         "#9b59ff",
    "ASX Finance":        "#00e5cc",
    "ASX Infrastructure": "#8ba3b8",
    "ASX Industrials":    "#aaaaff",
    "ASX ETF":            "#4a6380",
}

# ── ASX NEWS FEEDS ────────────────────────────────────────────────────────────
AU_NEWS_FEEDS = [
    {"url": "https://www.smh.com.au/rss/business.xml",
     "source": "SMH Business", "category": "australia"},
    {"url": "https://stockhead.com.au/feed/",
     "source": "Stockhead", "category": "australia"},
    {"url": "https://au.finance.yahoo.com/rss/topstories",
     "source": "Yahoo Finance AU", "category": "australia"},
    {"url": "https://seekingalpha.com/tag/australia/feed.xml",
     "source": "Seeking Alpha AU", "category": "australia"},
]


def fetch_asx_quotes(symbols: list[str] = None) -> dict:
    """
    Fetch live quotes for ASX tickers via Yahoo Finance v8 API.
    Returns dict keyed by symbol, with 'currency': 'AUD'.
    """
    from market_data import _yf_is_blocked
    if _yf_is_blocked():
        print("[ASX] Yahoo Finance rate-limited — skipping ASX quote fetch")
        return {}
    symbols = symbols or list(ASX_TICKERS.keys())
    results = {}
    for sym in symbols:
        try:
            time.sleep(0.35)
            data = _yf_chart(sym)
            if not data:
                continue
            meta = data["meta"]
            price = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
            prev = float(meta.get("previousClose") or price) or price
            change = price - prev
            change_pct = (change / prev * 100) if prev else 0
            currency = meta.get("currency", "AUD")
            results[sym] = {
                "symbol": sym,
                "name": ASX_TICKERS.get(sym, meta.get("longName") or meta.get("shortName") or sym),
                "price": round(price, 3),
                "change": round(change, 3),
                "change_pct": round(change_pct, 2),
                "prev_close": round(prev, 3),
                "currency": currency,
                "exchange": "ASX",
                "sector": ASX_SECTORS.get(sym, "ASX"),
                "updated": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print(f"[ASX] Quote failed for {sym}: {e}")
    return results


def fetch_asx_history(symbol: str, period: str = "5d", interval: str = "1d") -> list[dict]:
    """Fetch OHLCV history for an ASX ticker."""
    try:
        data = _yf_chart(symbol, interval=interval, period=period)
        if not data:
            return []
        ts = data.get("timestamp", [])
        quote = data.get("indicators", {}).get("quote", [{}])[0]
        opens, highs, lows = quote.get("open", []), quote.get("high", []), quote.get("low", [])
        closes, volumes = quote.get("close", []), quote.get("volume", [])
        records = []
        for i, t in enumerate(ts):
            if i >= len(closes) or closes[i] is None:
                continue
            records.append({
                "time": datetime.utcfromtimestamp(t).isoformat() + "Z",
                "open": round(float(opens[i] or closes[i]), 3),
                "high": round(float(highs[i] or closes[i]), 3),
                "low": round(float(lows[i] or closes[i]), 3),
                "close": round(float(closes[i]), 3),
                "volume": int(volumes[i] or 0) if i < len(volumes) else 0,
            })
        return records
    except Exception as e:
        print(f"[ASX] History failed for {symbol}: {e}")
        return []


def fetch_asx_company_info(symbol: str) -> dict | None:
    """
    Fetch company metadata for an ASX ticker via Yahoo Finance.
    Returns name, sector, industry, description, country, market_cap.
    """
    try:
        r = requests.get(
            _YF_SEARCH,
            params={"q": symbol, "lang": "en-AU", "region": "AU",
                    "quotesCount": 1, "newsCount": 0},
            headers=_HEADERS, timeout=8
        )
        if r.status_code != 200:
            return None
        quotes = r.json().get("quotes", [])
        if not quotes:
            return None
        q = quotes[0]
        return {
            "symbol": symbol,
            "name": q.get("longname") or q.get("shortname") or ASX_TICKERS.get(symbol, symbol),
            "exchange": q.get("exchange", "ASX"),
            "sector": ASX_SECTORS.get(symbol, q.get("sector", "ASX")),
            "industry": q.get("industry", ""),
            "country": "Australia",
            "currency": "AUD",
            "market_cap": q.get("marketCap"),
            "updated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"[ASX] Company info failed for {symbol}: {e}")
        return None


def fetch_asx_ticker_news(symbol: str, count: int = 5) -> list[dict]:
    """Fetch news items for a specific ASX ticker via Yahoo Finance search API."""
    try:
        r = requests.get(
            _YF_SEARCH,
            params={"q": symbol, "lang": "en-AU", "region": "AU",
                    "quotesCount": 0, "newsCount": count},
            headers=_HEADERS, timeout=8
        )
        if r.status_code != 200:
            return []
        items = []
        for n in r.json().get("news", []):
            items.append({
                "guid": n.get("uuid", ""),
                "title": n.get("title", ""),
                "url": n.get("link", ""),
                "source": n.get("publisher", "Yahoo Finance"),
                "category": "australia",
                "tickers": json_safe_tickers(n.get("relatedTickers", []), symbol),
                "sentiment_score": 0.0,
                "published_at": _ts_to_iso(n.get("providerPublishTime")),
                "fetched_at": datetime.utcnow().isoformat(),
                "summary": n.get("summary", ""),
            })
        return items
    except Exception as e:
        print(f"[ASX] Ticker news failed for {symbol}: {e}")
        return []


def fetch_au_news(watchlist_asx: list[str] = None) -> list[dict]:
    """
    Fetch Australian financial news from RSS feeds + Yahoo Finance per-ticker.
    Returns list of news item dicts compatible with memory_store.upsert_news_items.
    """
    import feedparser as _fp
    all_items = []
    seen_guids: set = set()

    # RSS feeds
    for feed in AU_NEWS_FEEDS:
        try:
            time.sleep(0.3)
            r = requests.get(feed["url"], headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }, timeout=10)
            parsed = _fp.parse(r.text)
            for entry in parsed.entries[:25]:
                guid = entry.get("id") or entry.get("link", "")
                if guid in seen_guids:
                    continue
                seen_guids.add(guid)
                pub = entry.get("published") or entry.get("updated") or ""
                summary = _strip_html(entry.get("summary", ""))
                title = entry.get("title", "")
                if not _is_financially_relevant(feed["source"], f"{title} {summary}"):
                    continue
                tickers = _extract_asx_tickers(
                    title + " " + summary
                )
                all_items.append({
                    "guid": guid,
                    "title": title,
                    "summary": summary[:500],
                    "url": entry.get("link", ""),
                    "source": feed["source"],
                    "category": "australia",
                    "tickers": ",".join(tickers[:5]),
                    "sentiment_score": 0.0,
                    "published_at": _parse_date(pub),
                    "fetched_at": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            print(f"[ASX News] Feed {feed['source']} error: {e}")

    # Per-ticker Yahoo Finance news for watchlist ASX stocks
    if watchlist_asx:
        for sym in watchlist_asx[:15]:
            time.sleep(0.4)
            news = fetch_asx_ticker_news(sym, count=3)
            for n in news:
                if n["guid"] not in seen_guids:
                    seen_guids.add(n["guid"])
                    all_items.append(n)

    print(f"[ASX News] Fetched {len(all_items)} items")
    return all_items


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _yf_chart(symbol: str, interval: str = "1d", period: str = "5d") -> dict | None:
    for base in (_YF_CHART, _YF_CHART2):
        try:
            r = requests.get(
                f"{base}/{symbol}?interval={interval}&range={period}",
                headers=_HEADERS, timeout=12
            )
            if r.status_code == 429:
                time.sleep(3)
                r = requests.get(
                    f"{base}/{symbol}?interval={interval}&range={period}",
                    headers=_HEADERS, timeout=12
                )
            r.raise_for_status()
            result = r.json().get("chart", {}).get("result")
            if result:
                return result[0]
        except Exception:
            continue
    return None


def _strip_html(text: str) -> str:
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()
    except Exception:
        return text


def _extract_asx_tickers(text: str) -> list[str]:
    """Extract .AX ticker symbols mentioned in text."""
    import re
    found = re.findall(r'\b([A-Z]{2,5})\.AX\b', text)
    # Also check for bare ASX codes that match our known list
    known_codes = {sym.replace(".AX", "") for sym in ASX_TICKERS}
    bare = re.findall(r'\b([A-Z]{3,5})\b', text)
    for code in bare:
        if code in known_codes:
            found.append(code + ".AX")
    return list(dict.fromkeys(found))  # deduplicate preserving order


def _parse_date(date_str: str) -> str:
    from email.utils import parsedate_to_datetime
    if not date_str:
        return datetime.utcnow().isoformat()
    try:
        return parsedate_to_datetime(date_str).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").isoformat()
        except Exception:
            return datetime.utcnow().isoformat()


def _ts_to_iso(ts) -> str:
    if not ts:
        return datetime.utcnow().isoformat()
    try:
        return datetime.utcfromtimestamp(int(ts)).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def json_safe_tickers(tickers, fallback: str) -> str:
    if not tickers:
        return fallback
    return ",".join(str(t) for t in tickers[:5])


def is_asx_ticker(symbol: str) -> bool:
    return symbol.endswith(".AX")
