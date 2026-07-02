"""X API v2 client using requests directly (no tweepy — Python 3.13+ compatible)."""
import re
import time
import requests
from urllib.parse import unquote
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import X_BEARER_TOKEN, X_SEARCH_QUERIES, SIGNAL_FETCH_LIMIT, WATCHLIST
from memory_store import insert_signal

_analyzer = SentimentIntensityAnalyzer()
CASHTAG_RE = re.compile(r'\$([A-Z]{1,5})(?:-USD)?', re.IGNORECASE)
_TICKER_SET = set(WATCHLIST)
_TICKER_SHORT = {t.replace("-USD", ""): t for t in WATCHLIST}

BASE = "https://api.twitter.com/2"


def _headers():
    token = unquote(X_BEARER_TOKEN)
    return {"Authorization": f"Bearer {token}"}


def _score(text: str) -> tuple:
    try:
        from finbert_sentiment import analyze_sentiment
        res = analyze_sentiment(text)
        if res is not None:
            score, stype = res
            return score, stype, "finbert"
    except Exception as e:
        print(f"[Twitter Client] FinBERT scoring error: {e}")

    s = _analyzer.polarity_scores(text)
    c = s["compound"]
    if c >= 0.05:
        return c, "bullish", "vader"
    elif c <= -0.05:
        return c, "bearish", "vader"
    return c, "neutral", "vader"


def _extract_asset(text: str) -> str | None:
    for m in CASHTAG_RE.findall(text.upper()):
        if m in _TICKER_SHORT:
            return _TICKER_SHORT[m]
        if m in _TICKER_SET:
            return m
        if m + "-USD" in _TICKER_SET:
            return m + "-USD"
    return None


def search_recent(query: str, max_results: int = 20) -> list[dict]:
    max_results = max(10, min(100, max_results))
    params = {
        "query": query + " -is:retweet lang:en",
        "max_results": max_results,
        "tweet.fields": "created_at,author_id,public_metrics",
        "user.fields": "username",
        "expansions": "author_id",
    }
    try:
        resp = requests.get(f"{BASE}/tweets/search/recent", headers=_headers(), params=params, timeout=15)
        if resp.status_code == 429:
            retry = int(resp.headers.get("x-rate-limit-reset", time.time() + 60)) - int(time.time()) + 2
            print(f"[X] Rate limited — reset in {retry}s")
            return []
        if resp.status_code != 200:
            print(f"[X] HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        tweets = data.get("data") or []
        users = {u["id"]: u["username"] for u in (data.get("includes") or {}).get("users", [])}
        results = []
        for t in tweets:
            text = t.get("text", "")
            score, stype, model = _score(text)
            asset = _extract_asset(text)
            author = "@" + users.get(t.get("author_id", ""), "unknown")
            metrics = t.get("public_metrics") or {}
            results.append({
                "id": t["id"],
                "text": text,
                "author": author,
                "sentiment_score": score,
                "signal_type": stype,
                "sentiment_model": model,
                "asset": asset,
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "created_at": t.get("created_at"),
            })
        return results
    except Exception as e:
        print(f"[X] Search error: {e}")
        return []


def fetch_signals(max_results: int = SIGNAL_FETCH_LIMIT, user_watchlist: list = None) -> list[dict]:
    """Fetch signals from X. Optionally add user-specific watchlist queries."""
    queries = list(X_SEARCH_QUERIES)
    if user_watchlist:
        # Build cashtag query from user's watchlist
        tickers = [s.replace("-USD", "") for s in user_watchlist[:10]]
        if tickers:
            queries.insert(0, " OR ".join(f"${t}" for t in tickers))

    collected = []
    per_query = max(10, max_results // len(queries))
    for query in queries:
        results = search_recent(query, max_results=per_query)
        for s in results:
            insert_signal(
                source="twitter",
                content=s["text"],
                asset=s["asset"],
                author=s["author"],
                sentiment_score=s["sentiment_score"],
                signal_type=s["signal_type"],
                sentiment_model=s.get("sentiment_model", "vader"),
                metadata={"id": s["id"], "likes": s["likes"], "retweets": s["retweets"]},
            )
        collected.extend(results)
        time.sleep(0.5)  # gentle rate limit buffer

    return collected


def score_text(text: str) -> tuple:
    score, stype, model = _score(text)
    return score, stype
