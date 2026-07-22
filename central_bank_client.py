"""Central bank statement semantic-delta analysis (FSI L4).

The signal is paragraph- and word-level *change* between consecutive FOMC
statements, not the statement text itself — the Fed's own statements are
~90% boilerplate reused meeting to meeting, so which words got added or
dropped is the actual data (e.g. "transitory" being dropped in Nov 2021
predated the real hiking cycle by weeks). Built entirely on stdlib difflib
plus the app's existing FinBERT/VADER scorer — no new model, no new
dependency, same zero-new-dependency posture as confluence_engine.py and
seasonality_engine.py.

Fed-only v1: federalreserve.gov publishes each statement at a predictable
URL keyed off the meeting's announcement date, already tracked in
calendar_client.py's FOMC_2026 schedule. RBA/ECB full statement text isn't
reliably scrapeable the same way (news_client.py only gets RBA headlines
via RSS, not the full statement) — left as a stretch goal, not attempted here.
"""
import difflib
import time
from datetime import date

import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from calendar_client import FOMC_2026

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_STATEMENT_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{date}a.htm"
_SKIP_PREFIXES = ("For media inquiries", "Implementation Note issued")

_vader = SentimentIntensityAnalyzer()


def _extract_statement_paragraphs(html: bytes) -> list[str]:
    """The Fed's press-release template repeats the same "col-xs-12 col-sm-8
    col-md-8" grid class for both the heading block and the body block —
    the body one is the only occurrence without "heading" also in its class
    list, so that's what disambiguates them."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("div", id="article")
    if not article:
        return []
    body = None
    for div in article.find_all("div", class_="col-sm-8"):
        classes = div.get("class", [])
        if "heading" not in classes:
            body = div
            break
    if not body:
        return []
    paragraphs = []
    for p in body.find_all("p"):
        text = p.get_text().strip()
        if not text or text.startswith(_SKIP_PREFIXES):
            continue
        paragraphs.append(text)
    return paragraphs


def fetch_statement(meeting_date: str) -> str | None:
    """meeting_date: YYYY-MM-DD, the announcement day (second date in each
    FOMC_2026 tuple). Returns paragraphs joined with blank lines, or None if
    not yet published / the fetch failed."""
    url = _STATEMENT_URL.format(date=meeting_date.replace("-", ""))
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        # federalreserve.gov doesn't send a charset in Content-Type, so
        # requests falls back to Latin-1 per RFC 2616 -- but the page body
        # is actually UTF-8 (real non-ASCII punctuation like en-dashes and
        # non-breaking hyphens appears raw, not as HTML entities), which
        # silently mojibake'd under r.text. Parsing r.content directly lets
        # BeautifulSoup's own encoding sniffing get this right.
        paragraphs = _extract_statement_paragraphs(r.content)
        return "\n\n".join(paragraphs) if paragraphs else None
    except requests.RequestException:
        return None


def _sentiment(text: str) -> float:
    text = text[:2000]
    try:
        from finbert_sentiment import analyze_sentiment
        res = analyze_sentiment(text)
        if res is not None:
            return res[0]
    except Exception:
        pass
    return _vader.polarity_scores(text)["compound"]


def _word_diff(old_paragraph: str, new_paragraph: str) -> dict:
    old_words, new_words = old_paragraph.split(), new_paragraph.split()
    sm = difflib.SequenceMatcher(None, old_words, new_words)
    added_words, removed_words = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            added_words.extend(new_words[j1:j2])
        if tag in ("delete", "replace"):
            removed_words.extend(old_words[i1:i2])
    return {
        "old_paragraph": old_paragraph,
        "new_paragraph": new_paragraph,
        "added_words": added_words,
        "removed_words": removed_words,
    }


def compute_delta(prior_text: str | None, current_text: str) -> dict:
    """Paragraph-level diff of `current_text` against `prior_text`. Wholly
    new/removed paragraphs go to added/removed; paragraphs that map roughly
    1:1 (a "replace" op) get a word-level diff instead, since that's where
    the real hawkish/dovish signal lives. No prior statement (first-ever
    fetch) just seeds the baseline — no sentiment_delta is possible yet."""
    current_paragraphs = [p for p in current_text.split("\n\n") if p.strip()]
    if not prior_text:
        return {"added": current_paragraphs, "removed": [], "changed": [], "sentiment_delta": None}

    prior_paragraphs = [p for p in prior_text.split("\n\n") if p.strip()]
    sm = difflib.SequenceMatcher(None, prior_paragraphs, current_paragraphs)
    added, removed, changed = [], [], []
    changed_old_text, changed_new_text = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added.extend(current_paragraphs[j1:j2])
        elif tag == "delete":
            removed.extend(prior_paragraphs[i1:i2])
        elif tag == "replace":
            old_chunk, new_chunk = prior_paragraphs[i1:i2], current_paragraphs[j1:j2]
            for old_p, new_p in zip(old_chunk, new_chunk):
                word_delta = _word_diff(old_p, new_p)
                if word_delta["added_words"] or word_delta["removed_words"]:
                    changed.append(word_delta)
                    changed_old_text.append(old_p)
                    changed_new_text.append(new_p)
            if len(old_chunk) > len(new_chunk):
                removed.extend(old_chunk[len(new_chunk):])
            elif len(new_chunk) > len(old_chunk):
                added.extend(new_chunk[len(old_chunk):])

    sentiment_delta = None
    if changed_old_text or changed_new_text:
        old_score = _sentiment(" ".join(changed_old_text)) if changed_old_text else 0.0
        new_score = _sentiment(" ".join(changed_new_text)) if changed_new_text else 0.0
        sentiment_delta = round(new_score - old_score, 3)

    return {"added": added, "removed": removed, "changed": changed, "sentiment_delta": sentiment_delta}


def _due_meeting_dates() -> list[str]:
    today = date.today().isoformat()
    return sorted(end for (_, end, _) in FOMC_2026 if end <= today)


def refresh_central_bank_deltas(bank: str = "Fed") -> list[dict]:
    """Idempotent: only fetches meeting dates that (a) have already happened
    and (b) aren't already stored, so it's safe to run on any cadence —
    daily cron or otherwise. On a cold DB this backfills every meeting that's
    happened so far this year, building the delta history retroactively."""
    from memory_store import get_central_bank_statement, save_central_bank_statement

    dates = _due_meeting_dates()
    results = []
    for i, meeting_date in enumerate(dates):
        if get_central_bank_statement(bank, meeting_date):
            continue
        text = fetch_statement(meeting_date)
        if not text:
            continue
        prior_date = dates[i - 1] if i > 0 else None
        prior_row = get_central_bank_statement(bank, prior_date) if prior_date else None
        prior_text = prior_row["raw_text"] if prior_row else None
        delta = compute_delta(prior_text, text)
        save_central_bank_statement(bank, meeting_date, prior_date, text, delta)
        results.append({"meeting_date": meeting_date, **delta})
        time.sleep(1)
    return results
