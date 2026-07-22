"""Federal Reserve Beige Book regional-conditions sentiment score -- a
qualitative national economic-sentiment signal (FSI L2, nlp_signal, #427).

Distinct from the FOMC post-meeting statement word-diff (#143, a short terse
policy-stance document): the Beige Book is a long narrative report on
real-economy conditions (employment, consumer spending, manufacturing,
prices) gathered from the 12 Federal Reserve Districts ahead of each FOMC
meeting, written in plain business language -- well suited to sentence-level
VADER scoring rather than a word-diff. Published ~8 times/year at a
predictable federalreserve.gov/monetarypolicy/beigebookYYYYMM.htm URL
pattern; this walks backward from the current month until a real release
page is found.

Feed r.content (bytes) to BeautifulSoup, never r.text -- requests' Latin-1
fallback silently corrupts UTF-8 on sources without an explicit charset
header (see project memory). Read-only public government text, same trust
boundary as news_client.py's RSS ingestion. No LLM call needed -- VADER is
already the app's standard lexicon-based scorer for this kind of text
(twitter_client.py, news_client.py).
"""
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from memory_store import get_latest_beige_book_sentiment, insert_beige_book_sentiment

_BASE_URL = "https://www.federalreserve.gov/monetarypolicy/beigebook{ym}.htm"
_CACHE_TTL_S = 24 * 3600  # releases are infrequent (~8/year), cache generously
_cache: dict = {"computed_at": 0.0, "data": None}
_vader = SentimentIntensityAnalyzer()


def _shift_month(year: int, month: int, back: int) -> tuple[int, int]:
    """month is 1-12; shift back by `back` months, wrapping year correctly
    (plain day-arithmetic subtraction drifts across variable month lengths)."""
    total = year * 12 + (month - 1) - back
    y, m0 = divmod(total, 12)
    return y, m0 + 1


def _find_latest_release(max_months_back: int = 6) -> tuple[str, bytes] | None:
    """Walk backward from the current month until a real release page is
    found. Returns (release_date "YYYY-MM-DD", raw html bytes) or None."""
    today = datetime.utcnow()
    for i in range(max_months_back):
        year, month = _shift_month(today.year, today.month, i)
        ym = f"{year:04d}{month:02d}"
        url = _BASE_URL.format(ym=ym)
        try:
            r = requests.get(url, timeout=15)
        except Exception:
            continue
        if r.status_code == 200:
            return f"{year:04d}-{month:02d}-01", r.content
    return None


def _score_text(html_bytes: bytes) -> float | None:
    """Extract body text and average the VADER compound score per sentence
    (short fragments like nav/footer links are filtered out by length)."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    scores = [_vader.polarity_scores(s)["compound"] for s in sentences if len(s) > 20]
    if not scores:
        return None
    return sum(scores) / len(scores)


def compute_beige_book_sentiment() -> dict | None:
    found = _find_latest_release()
    if not found:
        return None
    release_date, html_bytes = found

    composite = _score_text(html_bytes)
    if composite is None:
        return None
    composite = round(composite, 4)

    latest_row = get_latest_beige_book_sentiment()
    if latest_row and latest_row["release_date"] == release_date:
        # Already stored (cache refresh found no new release yet) -- reuse
        # the prior/delta captured when this release was first inserted,
        # rather than recomputing them against itself.
        prior_score = latest_row["prior_score"]
        score_delta = latest_row["score_delta"]
    else:
        prior_score = latest_row["composite_score"] if latest_row else None
        score_delta = round(composite - prior_score, 4) if prior_score is not None else None
        insert_beige_book_sentiment(release_date, composite, prior_score, score_delta)

    if composite > 0.15:
        rating = "positive"
    elif composite < -0.15:
        rating = "negative"
    else:
        rating = "neutral"

    return {
        "release_date": release_date,
        "composite_score": composite,
        "prior_score": prior_score,
        "score_delta": score_delta,
        "rating": rating,
    }


def get_beige_book_sentiment(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S (24h;
    releases are infrequent so there's no value refreshing more often)."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_beige_book_sentiment()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
