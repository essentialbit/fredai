"""Fred Recall storage layer -- FTS5 + optional local-embedding index over
Fred's own accumulated intelligence (news, signals, briefings, debates,
insider filings, thesis evidence, vault notes).

SQLite-only: no external vector DB, embeddings (when available) stored as
JSON via a direct HTTP call to Ollama's nomic-embed-text model (same
raw-HTTP pattern already used elsewhere in this codebase -- agent.py,
debate.py). rag_fts is an FTS5 external-content table over rag_chunks
(see the triggers in memory_store.py's init_db()) so retrieval never
depends on Ollama being up.

embed_text()/chunk_text() are the canonical implementations -- this used
to be duplicated in vault_semantic_search.py, which now imports them
from here instead (its vault content also lives in rag_chunks,
source_type='vault', migrated from the old standalone vault_embeddings
table).

Privacy boundary: user_id NULL means globally-visible content (news,
market-wide signals, debates -- nothing user-specific). Any row with a
non-NULL user_id (thesis evidence, personal briefings) is only ever
returned to that same user_id -- enforced in every retrieval query here,
never left to the caller.
"""
import json

import requests

from config import OLLAMA_URL
from memory_store import get_conn

_EMBED_MODEL = "nomic-embed-text"
_EMBED_TIMEOUT_S = 30
_CHUNK_CHARS = 2000  # ~500 tokens


def embed_text(text: str) -> list[float] | None:
    """None (never raises) if Ollama isn't reachable or the model isn't
    pulled -- every caller in this codebase already degrades gracefully
    on a None embedding."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": _EMBED_MODEL, "prompt": text},
            timeout=_EMBED_TIMEOUT_S,
        )
        if r.status_code != 200:
            return None
        return r.json().get("embedding") or None
    except requests.RequestException:
        return None


def chunk_text(text: str, chunk_chars: int = _CHUNK_CHARS) -> list[str]:
    chunks = []
    for i in range(0, len(text), chunk_chars):
        chunk = text[i:i + chunk_chars].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def upsert_chunk(source_type: str, source_id: str, content: str, title: str = "",
                  tickers: str = "", url: str = "", published_at: str | None = None,
                  user_id: int | None = None, embed: bool = True,
                  mtime: float | None = None) -> int:
    """Idempotent on (source_type, source_id). FTS row is always written
    (via the AFTER INSERT/UPDATE triggers); embedding is best-effort and
    None when Ollama isn't reachable -- retrieval degrades to FTS-only for
    that chunk, never blocks or fails."""
    embedding = None
    if embed:
        vec = embed_text(content[:2000])
        if vec:
            embedding = json.dumps(vec)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO rag_chunks
                   (source_type, source_id, user_id, title, content, tickers, url, published_at, embedding, mtime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_type, source_id) DO UPDATE SET
                   title=excluded.title, content=excluded.content, tickers=excluded.tickers,
                   url=excluded.url, published_at=excluded.published_at,
                   embedding=COALESCE(excluded.embedding, rag_chunks.embedding),
                   mtime=excluded.mtime,
                   indexed_at=CURRENT_TIMESTAMP""",
            (source_type, source_id, user_id, title, content, tickers, url, published_at, embedding, mtime),
        )
        row = conn.execute(
            "SELECT id FROM rag_chunks WHERE source_type=? AND source_id=?",
            (source_type, source_id),
        ).fetchone()
        return row["id"]


def delete_chunk(source_type: str, source_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM rag_chunks WHERE source_type=? AND source_id=?",
            (source_type, source_id),
        )


def get_chunks_missing_embeddings(limit: int = 200) -> list[dict]:
    """For the nightly embed-backlog job -- chunks written FTS-only because
    Ollama wasn't up at write time."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content FROM rag_chunks WHERE embedding IS NULL ORDER BY indexed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def set_embedding(chunk_id: int, embedding: list[float]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE rag_chunks SET embedding=? WHERE id=?",
            (json.dumps(embedding), chunk_id),
        )


def prune_old_chunks(days: int = 180) -> int:
    """News/signal chunks age out (matching news_items' own retention
    philosophy); briefings/debates/insider/entity-evidence/vault chunks are
    kept indefinitely -- they're low-volume and often exactly what a later
    'what did you think about X back then' question needs."""
    with get_conn() as conn:
        cur = conn.execute(
            """DELETE FROM rag_chunks
               WHERE source_type IN ('news', 'signal')
                 AND indexed_at < datetime('now', ?)""",
            (f"-{days} days",),
        )
        return cur.rowcount


def _row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("embedding"):
        d["embedding"] = json.loads(d["embedding"])
    return d


def fts_search(query_fts: str, user_id: int | None, limit: int = 30) -> list[dict]:
    """Raw FTS5 BM25 search, global rows plus this user's own rows only.
    query_fts must already be FTS5-query-safe (see rag_retriever._fts_escape)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, bm25(rag_fts) AS bm25_score
               FROM rag_fts f JOIN rag_chunks c ON c.id = f.rowid
               WHERE rag_fts MATCH ? AND (c.user_id IS NULL OR c.user_id = ?)
               ORDER BY bm25_score LIMIT ?""",
            (query_fts, user_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_embedded_chunks(user_id: int | None, limit: int = 5000) -> list[dict]:
    """Chunks with a stored embedding, global plus this user's own rows
    only, most recent first -- capped so the vector scan stays bounded on
    a large index (see rag_retriever's own cost-guard on top of this)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM rag_chunks
               WHERE embedding IS NOT NULL AND (user_id IS NULL OR user_id = ?)
               ORDER BY indexed_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_mtimes(source_type: str) -> dict:
    """{source_id: mtime} for every chunk of this source_type -- lets a
    caller do incremental reindexing (skip anything not newer than what's
    already stored)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_id, MAX(mtime) AS mtime FROM rag_chunks WHERE source_type=? GROUP BY source_id",
            (source_type,),
        ).fetchall()
        return {r["source_id"]: r["mtime"] for r in rows}


def count_chunks_by_source() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_type, COUNT(*) AS n FROM rag_chunks GROUP BY source_type"
        ).fetchall()
        return {r["source_type"]: r["n"] for r in rows}


# ── BACKFILL (one-time / idempotent re-run) ───────────────────────────────────

def backfill_all(batch_size: int = 500) -> dict:
    """Index existing DB history into rag_chunks. Idempotent -- upsert_chunk
    on the same source_id just refreshes content, never duplicates.
    FTS-only (embed=False) -- a large backfill embedding synchronously
    against Ollama would block for a very long time; the nightly
    embed-backlog job (see job_rag_embed_backlog in main.py) picks up
    every chunk here plus every write-time-indexed one. Returns counts
    per source_type."""
    counts = {}
    counts["news"] = _backfill_news(batch_size)
    counts["signal"] = _backfill_signals(batch_size)
    counts["briefing"] = _backfill_briefings(batch_size)
    counts["debate"] = _backfill_debates(batch_size)
    counts["insider"] = _backfill_insider(batch_size)
    counts["entity_evidence"] = _backfill_entity_evidence(batch_size)
    return counts


def _backfill_news(batch_size: int) -> int:
    """Keyed on guid, not the row id -- news_items' own natural idempotency
    key (see its ON CONFLICT(guid) DO NOTHING insert) and what the write-time
    index-on-write hook in news_client.py/main.py also uses, so a later
    backfill run never creates a duplicate chunk for an already-indexed
    article."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT guid, title, summary, url, source, tickers, published_at FROM news_items ORDER BY id DESC LIMIT ?",
            (batch_size,),
        ).fetchall()
    n = 0
    for r in rows:
        content = f"{r['title']}\n{r['summary'] or ''}".strip()
        if not content or not r["guid"]:
            continue
        upsert_chunk(
            "news", r["guid"], content, title=r["title"], tickers=r["tickers"] or "",
            url=r["url"] or "", published_at=r["published_at"], embed=False,
        )
        n += 1
    return n


def _backfill_signals(batch_size: int) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, source, asset, content, author, timestamp FROM signals ORDER BY id DESC LIMIT ?",
            (batch_size,),
        ).fetchall()
    n = 0
    for r in rows:
        if not r["content"]:
            continue
        title = f"{r['source']} signal" + (f" ({r['author']})" if r["author"] else "")
        upsert_chunk(
            "signal", str(r["id"]), r["content"], title=title,
            tickers=r["asset"] or "", published_at=r["timestamp"], embed=False,
        )
        n += 1
    return n


def _backfill_briefings(batch_size: int) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, timestamp, key_signals FROM summaries ORDER BY id DESC LIMIT ?",
            (batch_size,),
        ).fetchall()
    n = 0
    for r in rows:
        if not r["content"]:
            continue
        tickers = ",".join(json.loads(r["key_signals"] or "[]")) if r["key_signals"] else ""
        upsert_chunk(
            "briefing", str(r["id"]), r["content"], title="4h briefing",
            tickers=tickers, published_at=r["timestamp"], embed=False,
        )
        n += 1
    return n


def _backfill_debates(batch_size: int) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, bull_json, bear_json, verdict_json, created_at FROM ticker_debates ORDER BY id DESC LIMIT ?",
            (batch_size,),
        ).fetchall()
    n = 0
    for r in rows:
        try:
            bull = json.loads(r["bull_json"]).get("case", "") if r["bull_json"] else ""
            bear = json.loads(r["bear_json"]).get("case", "") if r["bear_json"] else ""
            verdict = json.loads(r["verdict_json"]) if r["verdict_json"] else {}
        except (json.JSONDecodeError, AttributeError):
            bull = bear = ""
            verdict = {}
        content = f"BULL: {bull}\nBEAR: {bear}\nVERDICT: {verdict.get('consensus', '')} (confidence {verdict.get('confidence', '')})"
        upsert_chunk(
            "debate", str(r["id"]), content, title=f"{r['ticker']} Bull/Bear debate",
            tickers=r["ticker"], published_at=r["created_at"], embed=False,
        )
        n += 1
    return n


def insider_source_id(ticker: str, owner_name: str, transaction_date: str,
                       transaction_code: str, shares) -> str:
    """Composite natural key matching insider_transactions' own UNIQUE
    constraint -- used as the rag_chunks source_id both here and at the
    index-on-write hook (main.py's job_insider_signals_refresh) so neither
    path needs the row's autoincrement id (insert_insider_transactions is a
    bulk executemany that doesn't expose one)."""
    return f"{ticker}:{owner_name}:{transaction_date}:{transaction_code}:{shares}"


def _backfill_insider(batch_size: int) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ticker, owner_name, owner_title, transaction_code, shares,
                      price_per_share, transaction_date
               FROM insider_transactions WHERE is_signal_code=1 ORDER BY id DESC LIMIT ?""",
            (batch_size,),
        ).fetchall()
    n = 0
    for r in rows:
        content = (
            f"{r['owner_name']} ({r['owner_title'] or 'insider'}) {r['transaction_code']} "
            f"{r['shares']} shares of {r['ticker']} at ${r['price_per_share']}"
        )
        source_id = insider_source_id(r["ticker"], r["owner_name"], r["transaction_date"],
                                       r["transaction_code"], r["shares"])
        upsert_chunk(
            "insider", source_id, content, title=f"{r['ticker']} Form 4 filing",
            tickers=r["ticker"], published_at=r["transaction_date"], embed=False,
        )
        n += 1
    return n


def _backfill_entity_evidence(batch_size: int) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ee.id, ee.note, ee.source, ee.created_at, te.name, te.user_id
               FROM entity_evidence ee JOIN tracked_entities te ON te.id = ee.entity_id
               ORDER BY ee.id DESC LIMIT ?""",
            (batch_size,),
        ).fetchall()
    n = 0
    for r in rows:
        if not r["note"]:
            continue
        upsert_chunk(
            "entity_evidence", str(r["id"]), r["note"], title=f"Evidence: {r['name']}",
            tickers=r["name"], published_at=r["created_at"], user_id=r["user_id"], embed=False,
        )
        n += 1
    return n
