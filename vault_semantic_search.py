"""Local semantic search over the user's Obsidian vault (FSI L4).

Scope is deliberately narrow: only obsidian_bridge.FREDAI_DIR
(AI/SMC/FredAI/ in the vault) is indexed -- an explicit privacy boundary,
not configurable without a code change. This is FredAI's own
signal/summary/improvement journal, not the user's full personal vault
(which also holds unrelated Claude-memory and other personal notes).

Storage/embedding now goes through rag_store.py (source_type='vault') as
part of Fred Recall -- this module is a thin wrapper preserving its own
public API (semantic_search/reindex_vault/get_vault_context) and privacy
boundary (FREDAI_DIR only, no other rag_chunks source_type touched here).
Previously vault chunks lived in their own vault_embeddings table with a
hand-rolled cosine scan; that table is now unused dead schema, left in
place rather than dropped since removing a table definition from
init_db() has no benefit (CREATE TABLE IF NOT EXISTS is a no-op either
way) and touching production schema beyond what's needed is unnecessary
risk.
"""
import json
import math
import os

from obsidian_bridge import FREDAI_DIR, vault_available
from rag_store import upsert_chunk, delete_chunk, get_mtimes, chunk_text, embed_text
from memory_store import get_conn

_TOP_K = 3
_MIN_SIMILARITY = 0.5


def _iter_vault_files():
    if not vault_available() or not FREDAI_DIR.exists():
        return
    for root, _, files in os.walk(FREDAI_DIR):
        for fname in files:
            if fname.endswith(".md"):
                yield os.path.join(root, fname)


def reindex_vault() -> dict:
    """Incrementally (re)index every .md file under FREDAI_DIR whose mtime
    is newer than what's already stored -- unchanged files are skipped
    rather than re-embedded. Returns {"indexed": N, "skipped": N}."""
    # get_mtimes keys are chunk-level source_ids ("path#0", "path#1", ...) --
    # collapse to one mtime per base path (all chunks of one file share it).
    stored_mtimes = {}
    for source_id, mtime in get_mtimes("vault").items():
        path = source_id.rsplit("#", 1)[0]
        stored_mtimes[path] = mtime
    indexed, skipped = 0, 0
    for path in _iter_vault_files():
        mtime = os.path.getmtime(path)
        if stored_mtimes.get(path) and stored_mtimes[path] >= mtime:
            skipped += 1
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        _delete_all_chunks_for_path(path)
        for i, chunk in enumerate(chunk_text(text)):
            upsert_chunk(
                "vault", f"{path}#{i}", chunk, title=os.path.basename(path),
                published_at=None, mtime=mtime,
            )
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}


def _delete_all_chunks_for_path(path: str) -> None:
    """A file can produce multiple chunks (source_id f'{path}#0', '#1', ...)
    -- delete every one before re-chunking so a shrunk file doesn't leave
    stale trailing chunks behind."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_id FROM rag_chunks WHERE source_type='vault' AND source_id LIKE ?",
            (f"{path}#%",),
        ).fetchall()
    for row in rows:
        delete_chunk("vault", row["source_id"])


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def semantic_search(query: str, top_k: int = _TOP_K) -> list[dict]:
    """Top-k vault chunks most similar to query, above _MIN_SIMILARITY.
    [] (never fabricated) if the vault isn't indexed yet or the local
    embedding call fails."""
    query_emb = embed_text(query)
    if not query_emb:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_id, content, embedding FROM rag_chunks WHERE source_type='vault' AND embedding IS NOT NULL"
        ).fetchall()
    scored = []
    for row in rows:
        embedding = json.loads(row["embedding"])
        sim = _cosine(query_emb, embedding)
        if sim >= _MIN_SIMILARITY:
            path = row["source_id"].rsplit("#", 1)[0]
            scored.append({"path": path, "chunk_text": row["content"], "similarity": round(sim, 3)})
    scored.sort(key=lambda r: r["similarity"], reverse=True)
    return scored[:top_k]


def get_vault_context(query: str, max_chars: int = 1200) -> str:
    """Formatted 'relevant notes' block for chat context injection, capped
    at max_chars. Empty string if nothing relevant found."""
    results = semantic_search(query)
    if not results:
        return ""
    lines = ["RELEVANT PERSONAL NOTES (from your FredAI vault journal):"]
    used = 0
    for r in results:
        line = f"- [{os.path.basename(r['path'])}] {r['chunk_text'][:300]}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
