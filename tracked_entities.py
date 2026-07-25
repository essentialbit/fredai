"""Tracked-entities thesis graph -- durable, user-driven memory for tickers,
sectors, themes, and people that a thesis keeps referring back to.

Unlike the static company-relationship graph that used to live in
graph_engine.py (removed 2026-07-04 for being hand-maintained and
disconnected from the rest of Fred's signal stack), entities here are
created on demand from real chat/API activity, carry a live thesis +
confidence, and accumulate an evidence log over time -- the graph only
grows where the user or Fred actually has something to say.
"""
from memory_store import get_conn

VALID_ENTITY_TYPES = {"ticker", "sector", "theme", "person"}


def create_entity(user_id: int, entity_type: str, name: str, thesis: str = "", confidence: float = 0.5) -> int:
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {VALID_ENTITY_TYPES}")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tracked_entities (user_id, entity_type, name, thesis, confidence)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, entity_type, name) DO UPDATE SET
                 thesis=excluded.thesis, confidence=excluded.confidence, updated_at=CURRENT_TIMESTAMP""",
            (user_id, entity_type, name.strip(), thesis, confidence),
        )
        row = conn.execute(
            "SELECT id FROM tracked_entities WHERE user_id=? AND entity_type=? AND name=?",
            (user_id, entity_type, name.strip()),
        ).fetchone()
        return row["id"]


def link_entities(user_id: int, from_entity_id: int, to_entity_id: int, relationship: str) -> int:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO entity_links (user_id, from_entity_id, to_entity_id, relationship)
               VALUES (?, ?, ?, ?)""",
            (user_id, from_entity_id, to_entity_id, relationship.strip()),
        )
        row = conn.execute(
            "SELECT id FROM entity_links WHERE from_entity_id=? AND to_entity_id=? AND relationship=?",
            (from_entity_id, to_entity_id, relationship.strip()),
        ).fetchone()
        return row["id"]


def add_evidence(entity_id: int, note: str, source: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entity_evidence (entity_id, note, source) VALUES (?, ?, ?)",
            (entity_id, note, source),
        )
        conn.execute(
            "UPDATE tracked_entities SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (entity_id,),
        )
        return cur.lastrowid


def get_entity(entity_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tracked_entities WHERE id=?", (entity_id,)).fetchone()
        if not row:
            return None
        entity = dict(row)
        entity["evidence"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM entity_evidence WHERE entity_id=? ORDER BY created_at DESC",
                (entity_id,),
            ).fetchall()
        ]
        entity["links"] = [
            dict(r) for r in conn.execute(
                """SELECT el.*, te.name AS to_name, te.entity_type AS to_type
                   FROM entity_links el JOIN tracked_entities te ON te.id = el.to_entity_id
                   WHERE el.from_entity_id=?""",
                (entity_id,),
            ).fetchall()
        ]
        return entity


def get_user_entities(user_id: int, entity_type: str | None = None, status: str = "active") -> list[dict]:
    with get_conn() as conn:
        if entity_type:
            rows = conn.execute(
                "SELECT * FROM tracked_entities WHERE user_id=? AND entity_type=? AND status=? ORDER BY updated_at DESC",
                (user_id, entity_type, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tracked_entities WHERE user_id=? AND status=? ORDER BY updated_at DESC",
                (user_id, status),
            ).fetchall()
        return [dict(r) for r in rows]


def get_entity_graph(user_id: int) -> dict:
    """Node/edge shape suitable for a simple force-graph render."""
    with get_conn() as conn:
        nodes = [dict(r) for r in conn.execute(
            "SELECT id, entity_type, name, thesis, confidence, status FROM tracked_entities WHERE user_id=? AND status='active'",
            (user_id,),
        ).fetchall()]
        edges = [dict(r) for r in conn.execute(
            "SELECT from_entity_id, to_entity_id, relationship FROM entity_links WHERE user_id=?",
            (user_id,),
        ).fetchall()]
        return {"nodes": nodes, "edges": edges}


def format_context_summary(user_id: int, limit: int = 5) -> str:
    """Compact plain-text summary for injection into Fred's chat/briefing context."""
    entities = get_user_entities(user_id)[:limit]
    if not entities:
        return ""
    lines = ["Active tracked theses:"]
    for e in entities:
        thesis = e["thesis"].strip() or "(no thesis notes yet)"
        lines.append(f"- {e['name']} ({e['entity_type']}, confidence {e['confidence']:.2f}): {thesis}")
    return "\n".join(lines)
