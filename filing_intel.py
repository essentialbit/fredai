"""FredAI Filing Intelligence (FSI L2/L4)
=====================================
Extends sec_client.py beyond Form 4 into 10-K/10-Q filing intelligence:
ingests Item 1A Risk Factors and Item 7 MD&A, paragraph-diffs each new
filing against the prior comparable one, and materiality-scores the
changes. Detecting a CHANGE in risk-factor language between filings is a
classic institutional edge that is pure NLP -- no new data dependency,
same EDGAR source sec_client.py already uses.

SEC fair-use posture: same as sec_client.py/sec_8k_client.py -- descriptive
User-Agent, one request at a time (no concurrency), a polite delay between
requests. Never re-fetches a filing document already in the `filings`
table (idempotent on accession_number) -- this doubles as the resumability
mechanism for a killed/restarted backfill: it naturally picks up wherever
it left off without a separate checkpoint/cursor table.

Filings can be huge -- extracted section text is capped at ~200KB (HARD
CONSTRAINT) before it's ever persisted; raw HTML above a sanity size cap
is skipped rather than parsed in full, to bound worst-case memory use.
"""
import difflib
import hashlib
import re
import time

import requests

from sec_client import _HEADERS, _get_cik, _SUBMISSIONS_URL
from memory_store import get_conn, insert_signal, insert_alert

_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodash}/{doc}"
_FORM_TYPES = ("10-K", "10-Q")
_MAX_RAW_HTML_BYTES = 8_000_000  # sanity cap -- skip pathologically large documents rather than parse in full
_MAX_SECTION_CHARS = 200_000  # HARD CONSTRAINT: cap stored text per filing at ~200KB
_MIN_SECTION_CHARS = 200  # below this, the extraction almost certainly hit a table-of-contents false positive

BACKFILL_FILINGS_PER_TICKER = 2

# Section-weighted materiality: Risk Factors language changes matter more
# than routine MD&A commentary (documented, not tuned against real data --
# revisit if live materiality scores don't track user intuition).
_SECTION_WEIGHT = {"risk_factors": 2.0, "mda": 1.0}

# High-signal vocabulary -- presence of any of these in a NEW or CHANGED
# paragraph is a strong materiality tell regardless of section. Documented
# constant per HARD CONSTRAINTS (same pattern as risk_rules.py's own
# keyword list).
HIGH_SIGNAL_TERMS = [
    "going concern", "material weakness", "covenant", "impairment",
    "investigation", "substantial doubt",
]

_RISK_FACTORS_START = [r"item\s+1a\.?\s*risk\s+factors"]
_RISK_FACTORS_END = [r"item\s+1b\.?\s", r"item\s+2\.?\s*(properties|management)"]
_MDA_START = [r"item\s+7\.?\s*management.s\s+discussion", r"item\s+2\.?\s*management.s\s+discussion"]
_MDA_END = [r"item\s+7a\.?\s", r"item\s+8\.?\s", r"item\s+3\.?\s*quantitative"]


# ── FETCH / PARSE ─────────────────────────────────────────────────────────

def list_filings(ticker: str, limit: int = 10) -> list[dict]:
    """Most recent 10-K/10-Q filings for ticker from EDGAR's submissions
    JSON (same endpoint/CIK map as sec_client.py). [] if not SEC-registered
    or no qualifying filings on record."""
    cik = _get_cik(ticker)
    if not cik:
        return []
    try:
        r = requests.get(_SUBMISSIONS_URL.format(cik=cik), headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception as e:
        print(f"[FilingIntel] Submissions fetch failed for {ticker}: {e}")
        return []

    forms = recent.get("form", [])
    idxs = [i for i, f in enumerate(forms) if f in _FORM_TYPES][:limit]
    out = []
    for i in idxs:
        out.append({
            "ticker": ticker.upper(),
            "cik": cik,
            "form_type": forms[i],
            "accession_number": recent["accessionNumber"][i],
            "filed_date": recent.get("filingDate", [None] * len(forms))[i],
            "fiscal_period": recent.get("reportDate", [None] * len(forms))[i],
            "primary_document": recent.get("primaryDocument", [None] * len(forms))[i],
        })
    return out


def _extract_section(text: str, start_patterns: list[str], end_patterns: list[str]) -> str | None:
    """Best-effort section extraction: takes the match of a start pattern
    with the LARGEST gap to the next end-pattern match, since a
    table-of-contents hit sits immediately before the next Item heading
    (near-zero gap) while the real section body doesn't. None if no
    plausible section is found (never fabricates content)."""
    start_re = re.compile("|".join(start_patterns), re.IGNORECASE)
    end_re = re.compile("|".join(end_patterns), re.IGNORECASE)
    starts = list(start_re.finditer(text))
    if not starts:
        return None
    best, best_len = None, 0
    for m in starts:
        end_m = end_re.search(text, m.end())
        section_end = end_m.start() if end_m else min(len(text), m.end() + _MAX_SECTION_CHARS)
        length = section_end - m.end()
        if length > best_len:
            best_len, best = length, text[m.end():section_end]
    if best is None or best_len < _MIN_SECTION_CHARS:
        return None
    return best.strip()[:_MAX_SECTION_CHARS]


def fetch_filing_sections(filing: dict) -> dict[str, str]:
    """Fetch the primary document and extract Risk Factors + MD&A as plain
    text. {} (never partial-fabricated) if the document can't be fetched,
    is pathologically large, or neither section is found."""
    if not filing.get("primary_document"):
        return {}
    cik_short = str(int(filing["cik"]))
    accession_nodash = filing["accession_number"].replace("-", "")
    url = _ARCHIVE_URL.format(cik_short=cik_short, accession_nodash=accession_nodash, doc=filing["primary_document"])
    try:
        r = requests.get(url, headers=_HEADERS, timeout=30)
        if r.status_code != 200 or len(r.content) > _MAX_RAW_HTML_BYTES:
            return {}
    except Exception as e:
        print(f"[FilingIntel] Document fetch failed for {filing['ticker']} ({filing['accession_number']}): {e}")
        return {}

    from bs4 import BeautifulSoup
    try:
        # r.content (bytes), not r.text -- avoids requests' Latin-1 fallback
        # silently corrupting UTF-8 on filings without an explicit charset
        # (same rule as news_client.py's federalreserve.gov handling).
        soup = BeautifulSoup(r.content, "html.parser")
        text = soup.get_text("\n", strip=True)
    except Exception:
        return {}

    sections = {}
    rf = _extract_section(text, _RISK_FACTORS_START, _RISK_FACTORS_END)
    if rf:
        sections["risk_factors"] = rf
    mda = _extract_section(text, _MDA_START, _MDA_END)
    if mda:
        sections["mda"] = mda
    return sections


# ── INGESTION ──────────────────────────────────────────────────────────────

def ingest_filing(filing: dict, delay_s: float = 0.3) -> int | None:
    """Fetch + persist one filing's sections. Idempotent on accession_number
    -- returns the EXISTING filing_id without re-fetching if already
    ingested (this is also the resumability mechanism for a killed/
    restarted backfill). None if the filing has no extractable sections."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM filings WHERE accession_number=?", (filing["accession_number"],)
        ).fetchone()
        if existing:
            return existing["id"]

    sections = fetch_filing_sections(filing)
    time.sleep(delay_s)
    if not sections:
        return None

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO filings (ticker, cik, form_type, accession_number, filed_date, fiscal_period)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(accession_number) DO UPDATE SET ticker=excluded.ticker""",
            (filing["ticker"], filing["cik"], filing["form_type"], filing["accession_number"],
             filing["filed_date"], filing["fiscal_period"]),
        )
        filing_id = cur.lastrowid or conn.execute(
            "SELECT id FROM filings WHERE accession_number=?", (filing["accession_number"],)
        ).fetchone()["id"]
        for section, content in sections.items():
            conn.execute(
                """INSERT INTO filing_sections (filing_id, section, content) VALUES (?, ?, ?)
                   ON CONFLICT(filing_id, section) DO UPDATE SET content=excluded.content""",
                (filing_id, section, content),
            )
    return filing_id


def _prior_filings_for_diff(ticker: str, current: dict) -> list[tuple[dict, str]]:
    """(prior_filing_row, comparison_label) pairs to diff `current` against.
    10-K: most recent PRIOR 10-K only ('prior_annual'). 10-Q: most recent
    PRIOR 10-Q ('prior_quarter') AND, if one exists in our own `filings`
    table, the filing whose fiscal_period lands closest to 12 months
    earlier ('prior_year') -- this only starts appearing once backfill has
    accumulated enough history, which is expected, not a bug."""
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            # filed_date < current's, not just != current's accession_number --
            # without this, processing filings out of chronological order (e.g.
            # a resumed/re-run cycle where a later filing already exists in the
            # table) can pick a NEWER filing as "prior" and diff backwards. Hit
            # in verification: a second cycle run over the same ticker produced
            # a reversed before/after pair because this filter was missing.
            "SELECT * FROM filings WHERE ticker=? AND accession_number!=? AND filed_date<? ORDER BY filed_date DESC",
            (ticker, current["accession_number"], current["filed_date"]),
        ).fetchall()]

    pairs = []
    if current["form_type"] == "10-K":
        prior_annual = next((r for r in rows if r["form_type"] == "10-K"), None)
        if prior_annual:
            pairs.append((prior_annual, "prior_annual"))
    else:
        prior_quarter = next((r for r in rows if r["form_type"] == "10-Q"), None)
        if prior_quarter:
            pairs.append((prior_quarter, "prior_quarter"))
        if current.get("fiscal_period"):
            from datetime import datetime
            try:
                cur_date = datetime.strptime(current["fiscal_period"], "%Y-%m-%d")
                candidates = [r for r in rows if r.get("fiscal_period")]
                best, best_gap = None, None
                for r in candidates:
                    try:
                        r_date = datetime.strptime(r["fiscal_period"], "%Y-%m-%d")
                    except ValueError:
                        continue
                    gap = abs((cur_date - r_date).days - 365)
                    if gap <= 45 and (best_gap is None or gap < best_gap):
                        best, best_gap = r, gap
                if best and best["accession_number"] != (pairs[0][0]["accession_number"] if pairs else None):
                    pairs.append((best, "prior_year"))
            except ValueError:
                pass
    return pairs


# ── DIFF ENGINE ───────────────────────────────────────────────────────────

def _split_paragraphs(text: str) -> list[str]:
    """Blank-line-ish splitting after get_text('\\n', strip=True) leaves one
    chunk per block-level element; filter out very short lines (page
    numbers, stray whitespace, table cell fragments) that aren't real
    prose paragraphs."""
    lines = [l.strip() for l in text.split("\n")]
    return [l for l in lines if len(l) >= 40]


def diff_paragraphs(prior_text: str, current_text: str) -> list[dict]:
    """Paragraph-level diff via difflib.SequenceMatcher opcodes. Each
    result: {change_type: added/removed/modified, before, after,
    change_ratio (0=identical, 1=completely different)}. Equal paragraphs
    are not returned -- only actual changes."""
    prior_paras = _split_paragraphs(prior_text)
    current_paras = _split_paragraphs(current_text)
    sm = difflib.SequenceMatcher(None, prior_paras, current_paras, autojunk=False)
    results = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        before_block = prior_paras[i1:i2]
        after_block = current_paras[j1:j2]
        if tag == "insert":
            for p in after_block:
                results.append({"change_type": "added", "before": "", "after": p, "change_ratio": 1.0})
        elif tag == "delete":
            for p in before_block:
                results.append({"change_type": "removed", "before": p, "after": "", "change_ratio": 1.0})
        elif tag == "replace":
            # Pair up modified paragraphs positionally within the replaced
            # block; any length mismatch spills into added/removed, same
            # spirit as insert/delete above.
            n = min(len(before_block), len(after_block))
            for k in range(n):
                ratio = 1.0 - difflib.SequenceMatcher(None, before_block[k], after_block[k]).ratio()
                results.append({"change_type": "modified", "before": before_block[k], "after": after_block[k],
                                 "change_ratio": round(ratio, 3)})
            for p in before_block[n:]:
                results.append({"change_type": "removed", "before": p, "after": "", "change_ratio": 1.0})
            for p in after_block[n:]:
                results.append({"change_type": "added", "before": "", "after": p, "change_ratio": 1.0})
    return results


# ── MATERIALITY SCORING ──────────────────────────────────────────────────

_vader = None


def _score_sentiment(text: str) -> float | None:
    """FinBERT if available, else VADER -- same degrade pattern as
    reddit_client.py/twitter_client.py. None (not fabricated) if neither
    is available or the text is empty."""
    if not text:
        return None
    try:
        from finbert_sentiment import analyze_sentiment
        res = analyze_sentiment(text)
        if res is not None:
            return res[0]
    except Exception:
        pass
    global _vader
    try:
        if _vader is None:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _vader = SentimentIntensityAnalyzer()
        return _vader.polarity_scores(text)["compound"]
    except Exception:
        return None


def _matched_high_signal_terms(text: str) -> list[str]:
    lower = text.lower()
    return [t for t in HIGH_SIGNAL_TERMS if t in lower]


def materiality_score(section: str, change_ratio: float, matched_terms: list[str],
                       sentiment_delta: float | None) -> float:
    """Section weight * change magnitude, plus a flat bonus per high-signal
    vocabulary hit, plus the magnitude of any sentiment swing (either
    direction -- a paragraph turning sharply more OR less cautious is both
    worth flagging). Documented, not fit against real data -- revisit if
    live scores don't track analyst intuition."""
    score = _SECTION_WEIGHT.get(section, 1.0) * change_ratio
    score += 0.5 * len(matched_terms)
    if sentiment_delta is not None:
        score += abs(sentiment_delta)
    return round(score, 3)


def _para_hash(before: str, after: str) -> str:
    return hashlib.sha256(f"{before}\x00{after}".encode()).hexdigest()[:16]


# ── ORCHESTRATION ─────────────────────────────────────────────────────────

def process_filing_pair(ticker: str, current_filing_id: int, prior_filing_id: int | None,
                         section: str, comparison: str, prior_text: str, current_text: str) -> list[dict]:
    """Diff one section between two filings, score each change, persist
    idempotently (UNIQUE on current/prior/section/para_hash -- a re-run
    over the same pair never duplicates rows). Returns the persisted diff
    rows (with their assigned id) for the caller to act on (signals,
    recall, alerts)."""
    diffs = diff_paragraphs(prior_text, current_text)
    persisted = []
    with get_conn() as conn:
        for d in diffs:
            matched = _matched_high_signal_terms(d["after"] or d["before"])
            before_sent = _score_sentiment(d["before"]) if d["before"] else None
            after_sent = _score_sentiment(d["after"]) if d["after"] else None
            sentiment_delta = (after_sent - before_sent) if (before_sent is not None and after_sent is not None) else None
            score = materiality_score(section, d["change_ratio"], matched, sentiment_delta)
            phash = _para_hash(d["before"], d["after"])
            cur = conn.execute(
                """INSERT OR IGNORE INTO filing_diffs
                       (ticker, section, comparison, current_filing_id, prior_filing_id, change_type,
                        before_text, after_text, para_hash, change_ratio, materiality_score,
                        sentiment_delta, high_signal_terms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticker, section, comparison, current_filing_id, prior_filing_id, d["change_type"],
                 d["before"], d["after"], phash, d["change_ratio"], score,
                 sentiment_delta, ",".join(matched)),
            )
            if cur.rowcount:
                row_id = cur.lastrowid
                persisted.append({**d, "id": row_id, "materiality_score": score,
                                   "high_signal_terms": matched, "section": section, "comparison": comparison})
    return persisted


def _surface_top_diffs(ticker: str, diffs: list[dict], materiality_threshold: float = 1.5) -> None:
    """Top-scoring diffs become signals (source='filing_diff'), get indexed
    into Fred Recall, and alert holders of this ticker. Never raises --
    one diff failing to index/alert must not block the rest."""
    top = sorted(diffs, key=lambda d: d["materiality_score"], reverse=True)
    for d in top:
        if d["materiality_score"] < materiality_threshold:
            continue
        snippet = d["after"] or d["before"]
        try:
            insert_signal(
                source="filing_diff", asset=ticker,
                content=f"[{d['section']}/{d['comparison']}] {d['change_type']}: {snippet[:300]}",
                sentiment_score=d.get("sentiment_delta") or 0.0,
                signal_type="bearish" if (d.get("sentiment_delta") or 0) < 0 else
                            ("bullish" if (d.get("sentiment_delta") or 0) > 0 else "neutral"),
            )
        except Exception as e:
            print(f"[FilingIntel] Signal insert failed for {ticker} diff {d.get('id')}: {e}")

        try:
            from rag_store import upsert_chunk
            upsert_chunk(
                "filing", f"diff-{d['id']}", snippet, title=f"{ticker} {d['section']} {d['change_type']}",
                tickers=ticker, embed=False,
            )
        except Exception:
            pass

        try:
            with get_conn() as conn:
                holders = conn.execute(
                    "SELECT DISTINCT user_id FROM portfolio WHERE symbol=? AND shares>0", (ticker,)
                ).fetchall()
            if holders:
                insert_alert(
                    level="warning", title=f"{ticker} filing language change",
                    message=f"{ticker}'s {d['section'].replace('_', ' ')} {d['change_type']} "
                            f"(materiality {d['materiality_score']:.2f}): {snippet[:200]}",
                    asset=ticker,
                )
        except Exception as e:
            print(f"[FilingIntel] Alert failed for {ticker} diff {d.get('id')}: {e}")


def run_filing_intel_cycle(tickers: list[str], backfill: bool = False, delay_s: float = 0.3) -> dict:
    """One pass: for each ticker, ingest new filings (or the last
    BACKFILL_FILINGS_PER_TICKER on first run) and diff each against its
    prior comparable filing(s). Sequential, rate-limited, resumable
    (ingest_filing skips anything already in `filings`). Never raises
    per-ticker."""
    results = {"tickers_processed": 0, "filings_ingested": 0, "diffs_found": 0, "diffs_persisted": 0}
    for ticker in tickers:
        try:
            results["tickers_processed"] += 1
            listing = list_filings(ticker, limit=BACKFILL_FILINGS_PER_TICKER if backfill else 3)
            time.sleep(delay_s)
            for filing in listing:
                filing_id = ingest_filing(filing, delay_s=delay_s)
                if filing_id is None:
                    continue
                results["filings_ingested"] += 1

                with get_conn() as conn:
                    sections = {r["section"]: r["content"] for r in conn.execute(
                        "SELECT section, content FROM filing_sections WHERE filing_id=?", (filing_id,)
                    ).fetchall()}
                if not sections:
                    continue

                prior_pairs = _prior_filings_for_diff(ticker, filing)
                for prior_row, comparison in prior_pairs:
                    with get_conn() as conn:
                        prior_sections = {r["section"]: r["content"] for r in conn.execute(
                            "SELECT section, content FROM filing_sections WHERE filing_id=?", (prior_row["id"],)
                        ).fetchall()}
                    for section, current_text in sections.items():
                        prior_text = prior_sections.get(section)
                        if not prior_text:
                            continue
                        diffs = process_filing_pair(
                            ticker, filing_id, prior_row["id"], section, comparison, prior_text, current_text,
                        )
                        results["diffs_found"] += len(diffs)
                        if diffs:
                            results["diffs_persisted"] += len(diffs)
                            _surface_top_diffs(ticker, diffs)
        except Exception as e:
            print(f"[FilingIntel] Cycle error for {ticker}: {e}")
    return results


# ── READ (API layer) ─────────────────────────────────────────────────────

def get_filing_watch(ticker: str, limit_diffs: int = 20) -> dict:
    """Latest filings + top language changes for the ticker-detail 'Filing
    Watch' view."""
    with get_conn() as conn:
        filings = [dict(r) for r in conn.execute(
            "SELECT * FROM filings WHERE ticker=? ORDER BY filed_date DESC LIMIT 5", (ticker.upper(),)
        ).fetchall()]
        diffs = [dict(r) for r in conn.execute(
            "SELECT * FROM filing_diffs WHERE ticker=? ORDER BY materiality_score DESC LIMIT ?",
            (ticker.upper(), limit_diffs),
        ).fetchall()]
    return {"ticker": ticker.upper(), "filings": filings, "top_diffs": diffs}
