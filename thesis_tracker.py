"""FredAI Thesis Tracker (FSI L4)
=====================================
Versioned investment theses that Fred Recall keeps alive with evidence --
a thesis, its falsifiable assumptions, and a running tally of
confirming/contradicting evidence, the way real PMs actually work.
Depends on Fred Recall (rag_store.py/rag_retriever.py) for the evidence
substrate.

Per-user isolation: theses are private to their owner. Ownership is
enforced at the API layer (main.py, same pattern as tracked_entities.py's
`entity["user_id"] != session["user_id"]` check) -- module functions here
operate on an id/row the caller has already authorized, matching that
existing precedent rather than duplicating the check at every layer.

Graceful degradation: decompose_thesis()/classify_evidence() are the only
LLM-dependent paths. If the provider is unavailable, decompose_thesis()
returns [] (caller falls back to manual assumption entry) and the nightly
auto-evidence loop just skips that thesis this cycle -- manual evidence
attach (add_evidence) never depends on an LLM at all.
"""
import json
from datetime import datetime, timedelta

from agent import _provider
from memory_store import get_conn, insert_alert

VALID_DIRECTIONS = {"long", "short"}
VALID_STATUS = {"active", "proven", "broken", "closed"}
VALID_ASSUMPTION_STATUS = {"intact", "weakening", "broken"}
VALID_STANCE = {"supporting", "contradicting", "neutral"}

MAX_AUTO_ATTACH_PER_DAY = 5  # naturally satisfied by the nightly (once/day) cadence of run_auto_evidence_loop
_CONTRADICTING_ALERT_THRESHOLD = 3  # contradicting items in the trailing 7d that flags an assumption weakening
_CONVICTION_HALFLIFE_DAYS = 14

_DECOMPOSE_PROMPT = """A user has written this investment thesis:

"{statement}"

Decompose it into 3-6 specific, falsifiable assumptions -- concrete claims \
that could individually be proven right or wrong by future evidence (not \
vague sentiment). Each should be short (one sentence).

Respond with ONLY a JSON object, no markdown fences:
{{"assumptions": ["...", "...", "..."]}}"""

_CLASSIFY_PROMPT = """THESIS: {statement}
ASSUMPTIONS:
{assumptions}

NEW EVIDENCE ITEM: {chunk_text}

Does this evidence item support, contradict, or is neutral to the thesis \
overall? Which specific assumption (by number) does it most relate to, if \
any?

Respond with ONLY a JSON object, no markdown fences:
{{"stance": "supporting"|"contradicting"|"neutral", "assumption_index": 0-{max_idx} or null, "reason": "one sentence"}}"""


def _parse_json(text: str) -> dict | None:
    try:
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        return json.loads(text)
    except Exception:
        return None


# ── CREATION ──────────────────────────────────────────────────────────────

def decompose_thesis(statement: str) -> list[str]:
    """LLM-assisted draft of 3-6 falsifiable assumptions -- a PREVIEW only,
    never persisted here. The user reviews/edits the result before
    create_thesis() actually saves it. [] (never fabricated) if the
    provider is unavailable or returns something unparseable -- caller
    falls back to manual assumption entry."""
    prompt = _DECOMPOSE_PROMPT.format(statement=statement)
    try:
        raw = _provider.complete(
            [{"role": "user", "content": prompt}],
            "You are an investment analyst helping decompose a thesis into testable claims.",
            tier="chat", max_tokens=400,
        )
        parsed = _parse_json(raw)
        if not parsed or not isinstance(parsed.get("assumptions"), list):
            return []
        return [a.strip() for a in parsed["assumptions"] if isinstance(a, str) and a.strip()][:6]
    except Exception:
        return []


def create_thesis(user_id: int, title: str, statement: str, direction: str,
                   tickers: str, assumptions: list[str], conviction: int = 50) -> int:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {VALID_DIRECTIONS}")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO theses (user_id, title, statement, direction, tickers, conviction)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, title.strip(), statement.strip(), direction, tickers.strip(), conviction),
        )
        thesis_id = cur.lastrowid
        for text in assumptions:
            text = (text or "").strip()
            if text:
                conn.execute(
                    "INSERT INTO thesis_assumptions (thesis_id, text) VALUES (?, ?)",
                    (thesis_id, text),
                )
    return thesis_id


# ── READ / UPDATE ─────────────────────────────────────────────────────────

def get_thesis(thesis_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
        if not row:
            return None
        thesis = dict(row)
        thesis["assumptions"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM thesis_assumptions WHERE thesis_id=? ORDER BY id",
                (thesis_id,),
            ).fetchall()
        ]
        thesis["evidence"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM thesis_evidence WHERE thesis_id=? ORDER BY created_at DESC",
                (thesis_id,),
            ).fetchall()
        ]
    thesis["suggested_conviction"] = suggested_conviction(thesis["evidence"])
    return thesis


def get_user_theses(user_id: int, status: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM theses WHERE user_id=? AND status=? ORDER BY updated_at DESC",
                (user_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM theses WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def update_thesis(thesis_id: int, **fields) -> None:
    """status/conviction/title/statement -- caller (API layer) validates
    ownership before calling. Column names are whitelisted here, never
    interpolated from caller-supplied keys directly."""
    allowed = {"status", "conviction", "title", "statement"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    if "status" in updates and updates["status"] not in VALID_STATUS:
        raise ValueError(f"status must be one of {VALID_STATUS}")
    set_clause = ", ".join(f"{k}=?" for k in updates) + ", updated_at=CURRENT_TIMESTAMP"
    with get_conn() as conn:
        conn.execute(f"UPDATE theses SET {set_clause} WHERE id=?", (*updates.values(), thesis_id))


def add_assumption(thesis_id: int, text: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO thesis_assumptions (thesis_id, text) VALUES (?, ?)",
            (thesis_id, text.strip()),
        )
        return cur.lastrowid


def update_assumption_status(assumption_id: int, status: str) -> None:
    if status not in VALID_ASSUMPTION_STATUS:
        raise ValueError(f"status must be one of {VALID_ASSUMPTION_STATUS}")
    with get_conn() as conn:
        conn.execute(
            "UPDATE thesis_assumptions SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, assumption_id),
        )


def add_evidence(thesis_id: int, stance: str, note: str = "", rag_chunk_id: int | None = None,
                  assumption_id: int | None = None, weight: float = 1.0, auto: bool = False) -> int | None:
    """Idempotent on (thesis_id, rag_chunk_id) when rag_chunk_id is given --
    returns None (not an id) if this exact chunk is already attached to
    this thesis, so callers (esp. the auto-attach loop) can detect a
    no-op without a separate existence check. Manual evidence (no
    rag_chunk_id) is never deduped this way -- SQLite treats each NULL in
    a UNIQUE column as distinct, so multiple free-text notes are fine."""
    if stance not in VALID_STANCE:
        raise ValueError(f"stance must be one of {VALID_STANCE}")
    with get_conn() as conn:
        if rag_chunk_id is not None:
            existing = conn.execute(
                "SELECT id FROM thesis_evidence WHERE thesis_id=? AND rag_chunk_id=?",
                (thesis_id, rag_chunk_id),
            ).fetchone()
            if existing:
                return None
        cur = conn.execute(
            """INSERT INTO thesis_evidence (thesis_id, assumption_id, rag_chunk_id, stance, weight, note, auto)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (thesis_id, assumption_id, rag_chunk_id, stance, weight, note, int(auto)),
        )
        conn.execute("UPDATE theses SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (thesis_id,))
        return cur.lastrowid


# ── CONVICTION ────────────────────────────────────────────────────────────

def suggested_conviction(evidence_rows: list[dict]) -> int | None:
    """Recency-weighted evidence balance -> a 0-100 suggested conviction,
    or None if there's no evidence yet (never fabricate a number from
    nothing). NEVER auto-applied to theses.conviction -- purely advisory,
    always shown side-by-side with the user's own stated conviction."""
    if not evidence_rows:
        return None
    now = datetime.utcnow()
    score = 0.0
    total_weight = 0.0
    for e in evidence_rows:
        stance_val = {"supporting": 1.0, "contradicting": -1.0, "neutral": 0.0}.get(e["stance"], 0.0)
        try:
            age_days = (now - datetime.strptime(e["created_at"][:19], "%Y-%m-%d %H:%M:%S")).total_seconds() / 86400
        except (ValueError, TypeError):
            age_days = 0
        recency = 0.5 ** (age_days / _CONVICTION_HALFLIFE_DAYS)
        w = (e.get("weight") or 1.0) * recency
        score += stance_val * w
        total_weight += w
    if total_weight == 0:
        return 50
    balance = score / total_weight  # -1..1
    return round(50 + balance * 50)


# ── ASSUMPTION HEALTH ─────────────────────────────────────────────────────

def check_assumption_health(thesis_id: int) -> list[dict]:
    """Marks assumptions weakening/broken when contradicting evidence has
    accumulated against them in the trailing 7 days, pushes an alert
    through the existing notification pipeline only on a NEW transition
    (not every call while the threshold is still met -- avoids alert
    spam). An assumption with no recent contradicting evidence recovers
    to 'intact' rather than staying flagged forever. Returns the
    assumptions that changed status this call."""
    thesis = get_thesis(thesis_id)
    if not thesis:
        return []
    changed = []
    since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    for a in thesis["assumptions"]:
        contradicting = sum(
            1 for e in thesis["evidence"]
            if e.get("assumption_id") == a["id"] and e["stance"] == "contradicting" and e["created_at"] >= since
        )
        new_status = a["status"]
        if contradicting >= _CONTRADICTING_ALERT_THRESHOLD * 2:
            new_status = "broken"
        elif contradicting >= _CONTRADICTING_ALERT_THRESHOLD:
            new_status = "weakening"
        elif a["status"] in ("weakening", "broken") and contradicting == 0:
            new_status = "intact"
        if new_status != a["status"]:
            update_assumption_status(a["id"], new_status)
            changed.append({
                "assumption_id": a["id"], "text": a["text"],
                "old_status": a["status"], "new_status": new_status,
            })
            if new_status in ("weakening", "broken"):
                insert_alert(
                    level="warning" if new_status == "weakening" else "danger",
                    title=f"Thesis assumption {new_status}",
                    message=f"Thesis '{thesis['title']}': assumption '{a['text']}' is {new_status} — "
                            f"{contradicting} contradicting item(s) this week.",
                    asset=(thesis.get("tickers") or "").split(",")[0].strip() or None,
                )
    return changed


# ── AUTO-EVIDENCE LOOP (nightly) ─────────────────────────────────────────

def classify_evidence(thesis: dict, assumptions: list[dict], chunk: dict) -> dict | None:
    """Cheap-tier LLM call: does this retrieved chunk support/contradict
    the thesis, and which assumption does it relate to. None (skip, don't
    fabricate) on any parse failure, empty assumption list, or provider
    error."""
    if not assumptions:
        return None
    assumption_list = "\n".join(f"{i}. {a['text']}" for i, a in enumerate(assumptions))
    prompt = _CLASSIFY_PROMPT.format(
        statement=thesis["statement"], assumptions=assumption_list,
        chunk_text=chunk["content"][:600], max_idx=len(assumptions) - 1,
    )
    try:
        raw = _provider.complete(
            [{"role": "user", "content": prompt}],
            "You are an investment analyst classifying evidence against a thesis.",
            tier="summary", max_tokens=200,
        )
        return _parse_json(raw)
    except Exception:
        return None


def run_auto_evidence_loop() -> dict:
    """Nightly job: for each active thesis, retrieve() fresh candidate
    evidence (query = statement + tickers), classify each with the cheap
    summary LLM tier, auto-attach (capped at MAX_AUTO_ATTACH_PER_DAY per
    thesis per run -- the job itself runs at most once/day), then
    re-check assumption health. Never raises per-thesis -- one thesis
    erroring (bad LLM output, retrieval hiccup) must not stop the rest."""
    from rag_retriever import retrieve

    with get_conn() as conn:
        theses = [dict(r) for r in conn.execute("SELECT * FROM theses WHERE status='active'").fetchall()]

    results = {"theses_processed": 0, "attached": 0, "alerts": 0}
    for t in theses:
        try:
            results["theses_processed"] += 1
            full = get_thesis(t["id"])
            if not full["assumptions"]:
                continue
            query = f"{t['statement']} {t['tickers']}".strip()
            chunks = retrieve(query, t["user_id"], k=10)
            attached_today = 0
            for chunk in chunks:
                if attached_today >= MAX_AUTO_ATTACH_PER_DAY:
                    break
                classification = classify_evidence(full, full["assumptions"], chunk)
                if not classification or classification.get("stance") not in VALID_STANCE:
                    continue
                idx = classification.get("assumption_index")
                assumption_id = None
                if isinstance(idx, int) and 0 <= idx < len(full["assumptions"]):
                    assumption_id = full["assumptions"][idx]["id"]
                new_id = add_evidence(
                    t["id"], classification["stance"], note=classification.get("reason", ""),
                    rag_chunk_id=chunk["id"], assumption_id=assumption_id, auto=True,
                )
                if new_id:
                    attached_today += 1
                    results["attached"] += 1
            changed = check_assumption_health(t["id"])
            results["alerts"] += sum(1 for c in changed if c["new_status"] in ("weakening", "broken"))
        except Exception as e:
            print(f"[ThesisTracker] Auto-evidence error for thesis {t['id']}: {e}")
    return results


# ── CHAT CONTEXT ──────────────────────────────────────────────────────────

def format_context_summary(user_id: int, limit: int = 5) -> str:
    """Compact plain-text summary of the user's active theses for chat
    context injection, mirroring tracked_entities.py's own pattern."""
    theses = get_user_theses(user_id, status="active")[:limit]
    if not theses:
        return ""
    lines = ["Active investment theses:"]
    for t in theses:
        lines.append(
            f"- \"{t['title']}\" ({t['direction']}, conviction {t['conviction']}/100, "
            f"tickers: {t['tickers'] or 'n/a'}): {t['statement'][:150]}"
        )
    return "\n".join(lines)
