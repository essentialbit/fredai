"""Local semantic search over the user's Obsidian vault (FSI L4).

Scope is deliberately narrow: only obsidian_bridge.FREDAI_DIR
(AI/SMC/FredAI/ in the vault) is indexed -- an explicit privacy boundary,
not configurable without a code change. This is FredAI's own
signal/summary/improvement journal, not the user's full personal vault
(which also holds unrelated Claude-memory and other personal notes).

Embeddings come from a local Ollama model (nomic-embed-text) via a direct
HTTP call to OLLAMA_URL/api/embeddings, matching the existing raw-HTTP
Ollama pattern already used elsewhere in this codebase (agent.py,
debate.py) rather than the `ollama` pip package. No external vector DB --
chunks and their embeddings are stored as JSON in sentinel.db (this
project is SQLite-only by design) and cosine similarity is computed in
Python, which is plenty for one vault subfolder's worth of notes.
"""
import math
import os

import requests

from config import OLLAMA_URL
from obsidian_bridge import FREDAI_DIR, vault_available
from memory_store import (
    upsert_vault_chunk, get_all_vault_chunks, get_vault_chunk_mtimes, delete_vault_chunks_for_path,
)

_EMBED_MODEL = "nomic-embed-text"
_CHUNK_CHARS = 2000  # ~500 tokens
_TOP_K = 3
_MIN_SIMILARITY = 0.5
_EMBED_TIMEOUT_S = 30


def _embed(text: str) -> list[float] | None:
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


def _chunk_text(text: str) -> list[str]:
    chunks = []
    for i in range(0, len(text), _CHUNK_CHARS):
        chunk = text[i:i + _CHUNK_CHARS].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


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
    stored_mtimes = get_vault_chunk_mtimes()
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
        delete_vault_chunks_for_path(path)
        for chunk in _chunk_text(text):
            embedding = _embed(chunk)
            if embedding:
                upsert_vault_chunk(path, chunk, embedding, mtime)
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}


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
    query_emb = _embed(query)
    if not query_emb:
        return []
    scored = []
    for row in get_all_vault_chunks():
        sim = _cosine(query_emb, row["embedding"])
        if sim >= _MIN_SIMILARITY:
            scored.append({"path": row["path"], "chunk_text": row["chunk_text"], "similarity": round(sim, 3)})
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
