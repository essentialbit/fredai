"""Fred Recall retrieval layer -- FTS5 (BM25) + optional cosine-similarity
search over rag_chunks, merged with Reciprocal Rank Fusion, then reranked
by recency decay and ticker-relevance boost.

Deterministic where it matters: ticker extraction and timeframe detection
are regex/set-membership, not LLM calls -- retrieve() must be fast and
never depend on an LLM being available. Embedding similarity is the only
optional step (skipped entirely when Ollama is down or the query itself
fails to embed); FTS5 alone is always enough to return something.
"""
import math
import re
import time
from datetime import datetime

import graph_engine
from config import WATCHLIST, DISPLAY_SYMBOLS
from rag_store import fts_search, get_embedded_chunks, embed_text

_RRF_K = 60
_MAX_VECTOR_SCAN = 4000  # cost guard -- see retrieve()'s warning below

# Half-life in days per source_type for the recency-decay rerank.
# entity_evidence/vault carry no decay (None) -- an old thesis note or
# vault entry is often exactly what a "what did you think back then"
# question needs, not something to bury for being old.
_RECENCY_HALFLIFE_DAYS = {
    "news": 7,
    "signal": 7,
    "briefing": 30,
    "debate": 30,
    "insider": 30,
    "entity_evidence": None,
    "vault": None,
}

_TICKER_BOOST = 1.3

_KNOWN_TICKERS = set(graph_engine.SECTORS.keys()) | set(WATCHLIST) | set(DISPLAY_SYMBOLS.keys())

_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z]{1,6})\b")
_BARE_TICKER_RE = re.compile(r"\b([A-Z]{1,6}(?:-USD)?)\b")

_TIMEFRAME_PATTERNS = [
    (re.compile(r"\btoday\b", re.IGNORECASE), "today"),
    (re.compile(r"\byesterday\b", re.IGNORECASE), "yesterday"),
    (re.compile(r"\blast week\b", re.IGNORECASE), "last_week"),
    (re.compile(r"\bthis week\b", re.IGNORECASE), "this_week"),
    (re.compile(r"\blast month\b", re.IGNORECASE), "last_month"),
    (re.compile(r"\bsince the fed\b", re.IGNORECASE), "since_fed"),
    (re.compile(r"\bsince earnings\b", re.IGNORECASE), "since_earnings"),
]


def parse_query(query: str) -> dict:
    """Deterministic extraction -- no LLM call. Returns
    {"tickers": [...], "timeframe": str|None}."""
    tickers = set(m.group(1) for m in _DOLLAR_TICKER_RE.finditer(query))
    for m in _BARE_TICKER_RE.finditer(query.upper()):
        if m.group(1) in _KNOWN_TICKERS:
            tickers.add(m.group(1))
    timeframe = None
    for pattern, label in _TIMEFRAME_PATTERNS:
        if pattern.search(query):
            timeframe = label
            break
    return {"tickers": sorted(tickers), "timeframe": timeframe}


def _fts_escape(query: str) -> str:
    """FTS5 MATCH treats the query as a mini query language (AND/OR/NOT,
    quoting, column filters...) -- a raw user string can throw a syntax
    error or mean something unintended. Reduce to a safe OR-of-terms:
    strip everything but words, wrap in double quotes (literal-phrase
    tokens), join with OR. Empty query -> empty string (caller must check)."""
    terms = re.findall(r"[A-Za-z0-9]+", query)
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _recency_weight(source_type: str, published_at: str | None, indexed_at: str | None) -> float:
    halflife = _RECENCY_HALFLIFE_DAYS.get(source_type)
    if halflife is None:
        return 1.0
    ts = published_at or indexed_at
    if not ts:
        return 1.0
    try:
        # SQLite CURRENT_TIMESTAMP format ("%Y-%m-%d %H:%M:%S") -- see the
        # timestamp-comparison rule already established elsewhere in this
        # codebase (memory_store.py) for why this format, not isoformat().
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        age_days = (datetime.utcnow() - dt).total_seconds() / 86400
    except ValueError:
        return 1.0
    return 0.5 ** (age_days / halflife)


def _rrf_merge(fts_ranked: list[dict], vec_ranked: list[dict]) -> dict:
    """Reciprocal Rank Fusion: score = sum(1 / (k + rank)) across the
    ranked lists a chunk appears in. Returns {chunk_id: (chunk, rrf_score)}."""
    scores: dict[int, float] = {}
    chunks: dict[int, dict] = {}
    for rank, chunk in enumerate(fts_ranked):
        scores[chunk["id"]] = scores.get(chunk["id"], 0.0) + 1.0 / (_RRF_K + rank + 1)
        chunks[chunk["id"]] = chunk
    for rank, chunk in enumerate(vec_ranked):
        scores[chunk["id"]] = scores.get(chunk["id"], 0.0) + 1.0 / (_RRF_K + rank + 1)
        chunks[chunk["id"]] = chunk
    return {cid: (chunks[cid], score) for cid, score in scores.items()}


def retrieve(query: str, user_id: int | None, k: int = 6) -> list[dict]:
    """Full retrieval: FTS5 always runs; cosine-over-embeddings runs only
    if Ollama responds to the query embed. Merge via RRF, then rerank by
    recency decay * ticker boost. Returns up to k chunks with
    source_type, title, url, published_at, score. Never raises -- an
    empty query or total retrieval failure returns []."""
    start = time.monotonic()
    parsed = parse_query(query)

    fts_query = _fts_escape(query)
    fts_ranked = fts_search(fts_query, user_id, limit=30) if fts_query else []

    vec_ranked = []
    query_emb = embed_text(query)
    if query_emb:
        embedded = get_embedded_chunks(user_id, limit=_MAX_VECTOR_SCAN + 1)
        if len(embedded) > _MAX_VECTOR_SCAN:
            print(f"[RAG] embedded-chunk count ({len(embedded)}) exceeds scan budget "
                  f"({_MAX_VECTOR_SCAN}) -- skipping vector path this call, consider "
                  f"pruning or a reindex. FTS results still returned.")
        else:
            scored = [(c, _cosine(query_emb, c["embedding"])) for c in embedded]
            scored.sort(key=lambda x: x[1], reverse=True)
            vec_ranked = [c for c, sim in scored[:30] if sim > 0]

    merged = _rrf_merge(fts_ranked, vec_ranked)

    results = []
    for chunk, rrf_score in merged.values():
        weight = _recency_weight(chunk["source_type"], chunk.get("published_at"), chunk.get("indexed_at"))
        chunk_tickers = set(t.strip().upper() for t in (chunk.get("tickers") or "").split(",") if t.strip())
        if parsed["tickers"] and chunk_tickers & set(parsed["tickers"]):
            weight *= _TICKER_BOOST
        results.append({
            "id": chunk["id"],
            "source_type": chunk["source_type"],
            "title": chunk.get("title") or "",
            "url": chunk.get("url") or "",
            "published_at": chunk.get("published_at"),
            "content": chunk["content"],
            "score": round(rrf_score * weight, 5),
        })
    results.sort(key=lambda r: r["score"], reverse=True)

    elapsed_ms = (time.monotonic() - start) * 1000
    if elapsed_ms > 300:
        print(f"[RAG] retrieve() took {elapsed_ms:.0f}ms (budget 300ms) for query {query!r}")

    return results[:k]


def format_context(chunks: list[dict]) -> str:
    """Compact citable block: [source_type · title/source · date · tickers]
    content, capped implicitly by the caller trimming chunk count (see
    agent.py's ~1500 token budget note)."""
    if not chunks:
        return ""
    lines = []
    for c in chunks:
        date = (c.get("published_at") or "")[:10] or "undated"
        tag = f"[{c['source_type']} · {c['title'] or 'untitled'} · {date}]"
        lines.append(f"{tag} {c['content'][:400]}")
    return "\n".join(lines)
