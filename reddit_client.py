"""Reddit retail-sentiment client -- public Atom feeds, no API key/auth.

Polls r/wallstreetbets and r/investing via Reddit's `.rss` (Atom) feeds --
verified live: Reddit's `/hot.json` anonymous JSON endpoint now 403s
unconditionally regardless of User-Agent (its anti-bot posture has tightened
since #58 was originally specced), but the `.rss` feed still serves real,
unauthenticated content with a browser-style UA. Reddit also rate-limits
aggressively on rapid repeat requests -- callers must space out polls
(the scheduled job here runs hourly, well within safe bounds; keep the
inter-subreddit sleep below when adding subreddits).

Scored and ticker-linked exactly like twitter_client.py/news_client.py, and
inserted into the same `signals` table so trending/summaries/Fred's chat
context pick Reddit signals up for free, no separate storage or UI needed.
"""
import re
import time

import feedparser
import requests
from bs4 import BeautifulSoup

from config import WATCHLIST
from memory_store import insert_signal, get_signals

# Matches news_client.py's _TICKER_MENTION convention: bare uppercase word
# OR cashtag, in one pass. WATCHLIST membership (checked below) is the real
# filter -- it's what keeps forum acronyms like "YOLO"/"DD"/"CEO" from being
# mistaken for tickers, not the regex itself.
_TICKER_MENTION = re.compile(r'\b([A-Z]{2,5})(?:\s*-\s*USD)?\b|\$([A-Z]{1,5})\b')
_TICKER_SHORT = {t.replace("-USD", ""): t for t in WATCHLIST}
_TICKER_SET = set(WATCHLIST)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

SUBREDDITS = ["wallstreetbets", "investing"]

_vader = None


def _score(text: str) -> tuple[float, str, str]:
    try:
        from finbert_sentiment import analyze_sentiment
        res = analyze_sentiment(text)
        if res is not None:
            score, stype = res
            return score, stype, "finbert"
    except Exception as e:
        print(f"[Reddit] FinBERT scoring error: {e}")

    global _vader
    if _vader is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader = SentimentIntensityAnalyzer()
    c = _vader.polarity_scores(text)["compound"]
    stype = "bullish" if c >= 0.05 else "bearish" if c <= -0.05 else "neutral"
    return round(c, 3), stype, "vader"


def _extract_tickers(text: str) -> list[str]:
    found = set()
    for bare, cash in _TICKER_MENTION.findall(text):
        sym = bare or cash
        if sym in _TICKER_SHORT:
            found.add(_TICKER_SHORT[sym])
        elif sym in _TICKER_SET:
            found.add(sym)

    if not found:
        try:
            from signal_processor import extract_and_link_tickers
            found.update(extract_and_link_tickers(text))
        except Exception:
            pass

    return sorted(found)


def _recently_seen_ids(hours: int = 48) -> set:
    seen = set()
    import json
    for s in get_signals(hours=hours, limit=1000):
        if not str(s.get("source", "")).startswith("reddit"):
            continue
        try:
            meta = json.loads(s.get("metadata") or "{}")
            pid = meta.get("id")
            if pid:
                seen.add(pid)
        except Exception:
            continue
    return seen


def _fetch_subreddit(subreddit: str, limit: int = 25) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/.rss"
    try:
        resp = requests.get(url, headers=_HEADERS, params={"limit": limit}, timeout=12)
        if resp.status_code == 429:
            print(f"[Reddit] r/{subreddit} rate limited")
            return []
        if resp.status_code != 200:
            print(f"[Reddit] r/{subreddit} HTTP {resp.status_code}")
            return []
        feed = feedparser.parse(resp.text)
    except Exception as e:
        print(f"[Reddit] r/{subreddit} fetch error: {e}")
        return []

    items = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        raw_content = ""
        if entry.get("content"):
            raw_content = entry["content"][0].get("value", "")
        elif entry.get("summary"):
            raw_content = entry.get("summary", "")
        body = BeautifulSoup(raw_content, "html.parser").get_text(" ", strip=True)[:500]

        text = f"{title} {body}".strip()
        tickers = _extract_tickers(text)
        if not tickers:
            continue

        score, stype, model = _score(text)
        post_id = (entry.get("id") or "").rsplit("_", 1)[-1] or entry.get("id", "")
        items.append({
            "id": post_id,
            "text": text[:500],
            "tickers": tickers,
            "sentiment_score": score,
            "signal_type": stype,
            "sentiment_model": model,
            "subreddit": subreddit,
            "author": (entry.get("author") or "unknown").strip(),
            "permalink": entry.get("link", ""),
        })
    return items


def fetch_reddit_signals(limit_per_sub: int = 25) -> list[dict]:
    """Poll all tracked subreddits, dedup against recently-stored posts, insert
    new ticker-linked signals, and return what was newly collected."""
    already_seen = _recently_seen_ids()
    collected = []

    for sub in SUBREDDITS:
        for post in _fetch_subreddit(sub, limit=limit_per_sub):
            if post["id"] in already_seen:
                continue
            for asset in post["tickers"]:
                signal_id = insert_signal(
                    source="reddit",
                    content=post["text"],
                    asset=asset,
                    author=post["author"],
                    sentiment_score=post["sentiment_score"],
                    signal_type=post["signal_type"],
                    sentiment_model=post["sentiment_model"],
                    metadata={
                        "id": post["id"],
                        "subreddit": post["subreddit"],
                        "permalink": post["permalink"],
                    },
                )
                _index_signal_for_recall(signal_id, "reddit", post["author"], post["text"], asset)
            collected.append(post)
        time.sleep(2.0)  # Reddit rate-limits aggressively on rapid repeat requests

    return collected


def _index_signal_for_recall(signal_id: int, source: str, author: str, content: str, asset: str) -> None:
    """Fred Recall write-time hook -- FTS-only (embed=False), the nightly
    embed-backlog job picks up embeddings later. Never blocks/fails the
    caller."""
    try:
        from rag_store import upsert_chunk
        title = f"{source} signal" + (f" ({author})" if author else "")
        upsert_chunk("signal", str(signal_id), content, title=title, tickers=asset or "", embed=False)
    except Exception:
        pass
