"""
FredAI Collaboration Board — Cross-Agent Debate Cycle
=======================================================
Each agent reviews the OTHER agent's open proposals (GitHub Issues labeled
agent-proposal) and posts a stance — agree / disagree / escalate — with a
confidence score and rationale. Combined with each agent's historical
track record (memory_store.get_track_record), this produces a weighted
consensus score, posted as a comment + label, that a future auto-merge
gate can key off (alongside risk_rules.classify_risk — high-risk proposals
never auto-merge regardless of consensus).
"""

import json
import re

from community import _gh_get, _gh_post, _gh_delete, GITHUB_REPO
from dotenv import load_dotenv
load_dotenv()  # Ensure .env is parsed into os.environ before community.py loads GITHUB_TOKEN

from community import _gh_get, _gh_post, GITHUB_REPO
from github_sync import get_open_proposal_issues, _ensure_label
from memory_store import get_track_record


_STANCE_MARKER = re.compile(r"<!--fredai:stance:(claude|gemini)-->")
_IMPACT_RE = re.compile(r"Impact score:\*\*\s*([\d.]+)")
_PROPOSED_BY_LABEL_RE = re.compile(r"^proposed-by:(claude|gemini)$")
_CONSENSUS_LABEL_RE = re.compile(r"^consensus:([\d.]+)$")
_STANCE_COMMENT_RE = re.compile(
    r"\*\*Stance \((claude|gemini)\):\*\*\s*(agree|disagree|escalate)\s*\(confidence\s*([\d.]+)\)"
)
_STALE_CONSENSUS_THRESHOLD = 0.02

_STANCE_PROMPT = """You are reviewing a proposal from your collaborating AI partner on FredAI's \
self-improvement board. FredAI's mission is to become the world's first Financial \
Super Intelligence (FSI levels L1-L6, see MISSION.md).

PROPOSAL:
{body}

Evaluate: does this genuinely advance the FSI mission, is the scope/estimate \
realistic, is there a simpler or better approach, any risk worth flagging?

Respond with ONLY a JSON object, no markdown fences:
{{"stance": "agree"|"disagree"|"escalate", "confidence": 0.0-1.0, "rationale": "1-3 sentences"}}"""


def _other_agent(proposed_by: str | None) -> str | None:
    """Only two agents ever review each other's proposals. Treat any label
    variant other than an exact "gemini" match as Claude-authored (e.g. a
    proposal posted with proposed_by="claude_rnd" or the insert_feature_proposal
    default "rnd_cycle") rather than silently skipping the issue forever --
    #176/#182 both went unreviewed for cycles because of an exact-match miss."""
    if not proposed_by:
        return None
    return "claude" if proposed_by == "gemini" else "gemini"


def _already_reviewed_by(comments: list, agent: str) -> bool:
    return any(
        (m := _STANCE_MARKER.search(c.get("body", ""))) and m.group(1) == agent
        for c in comments
    )


def _parse_stance(text: str) -> dict | None:
    try:
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        data = json.loads(text)
        if data.get("stance") in ("agree", "disagree", "escalate") and "confidence" in data:
            return data
    except Exception:
        pass
    return None


def _get_stance_claude(body: str) -> dict | None:
    import anthropic
    from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL_SUMMARY
    if ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("your_"):
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=ANTHROPIC_MODEL_SUMMARY, max_tokens=300,
                messages=[{"role": "user", "content": _STANCE_PROMPT.format(body=body)}],
            )
            parsed = _parse_stance(resp.content[0].text)
            if parsed:
                return parsed
        except Exception as e:
            print(f"[Debate] Claude stance API error: {e}")

    # Fallback to local Ollama (free, offline)
    try:
        import requests
        from config import OLLAMA_URL, OLLAMA_MODEL
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": _STANCE_PROMPT.format(body=body)}],
            "stream": False,
            "options": {"num_predict": 300}
        }
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        if r.status_code == 200:
            text = r.json()["message"]["content"]
            parsed = _parse_stance(text)
            if parsed:
                print(f"[Debate] Claude stance generated via Ollama fallback ({OLLAMA_MODEL})")
                return parsed
    except Exception as ollama_err:
        print(f"[Debate] Claude stance Ollama fallback error: {ollama_err}")
    return None


def _get_stance_gemini(body: str) -> dict | None:
    import requests
    from config import GEMINI_API_KEY, GEMINI_MODEL_SUMMARY
    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("your_"):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_SUMMARY}:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": _STANCE_PROMPT.format(body=body)}]}]}
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                parsed = _parse_stance(text)
                if parsed:
                    return parsed
            else:
                print(f"[Debate] Gemini stance API error: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"[Debate] Gemini stance API error: {e}")

    # Fallback to local Ollama (free, offline)
    try:
        from config import OLLAMA_URL, OLLAMA_MODEL
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": _STANCE_PROMPT.format(body=body)}],
            "stream": False,
            "options": {"num_predict": 300}
        }
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        if r.status_code == 200:
            text = r.json()["message"]["content"]
            parsed = _parse_stance(text)
            if parsed:
                print(f"[Debate] Gemini stance generated via Ollama fallback ({OLLAMA_MODEL})")
                return parsed
    except Exception as ollama_err:
        print(f"[Debate] Gemini stance Ollama fallback error: {ollama_err}")
    return None



def compute_consensus(proposer: str, reviewer: str, impact_score: float, reviewer_stance: dict) -> float:
    def accuracy(agent: str) -> float:
        rec = get_track_record(agent)
        if rec["proposals_implemented"] >= 5:
            return rec["proposals_succeeded"] / rec["proposals_implemented"]
        return 0.7  # cold-start default until there's a real track record

    confidence_proposer = max(0.0, min(1.0, (impact_score or 5.0) / 10))
    confidence_reviewer = max(0.0, min(1.0, float(reviewer_stance.get("confidence", 0.5))))

    consensus = (
        confidence_proposer * accuracy(proposer) * 0.5
        + confidence_reviewer * accuracy(reviewer) * 0.5
    )
    if reviewer_stance["stance"] == "disagree":
        consensus *= 0.3
    elif reviewer_stance["stance"] == "escalate":
        consensus = 0.0
    return round(consensus, 3)


def run_debate_cycle() -> dict:
    summary = {"issues_checked": 0, "stances_posted": 0, "errors": 0}
    issues = get_open_proposal_issues()
    summary["issues_checked"] = len(issues)

    for issue in issues:
        labels = [l["name"] for l in issue.get("labels", [])]
        proposed_by = next(
            (l.split(":", 1)[1] for l in labels if l.startswith("proposed-by:")), None
        )
        reviewer = _other_agent(proposed_by)
        if not reviewer:
            continue

        comments = _gh_get(f"repos/{GITHUB_REPO}/issues/{issue['number']}/comments") or []
        if _already_reviewed_by(comments, reviewer):
            continue

        body = issue.get("body", "") or ""
        stance = _get_stance_claude(body) if reviewer == "claude" else _get_stance_gemini(body)
        if not stance:
            summary["errors"] += 1
            continue

        impact_match = _IMPACT_RE.search(body)
        impact_score = float(impact_match.group(1)) if impact_match else 5.0
        consensus = compute_consensus(proposed_by, reviewer, impact_score, stance)

        comment_body = "\n".join([
            f"**Stance ({reviewer}):** {stance['stance']} (confidence {stance['confidence']:.2f})",
            f"**Rationale:** {stance['rationale']}",
            f"**Consensus score:** {consensus}",
            f"<!--fredai:stance:{reviewer}-->",
        ])
        _gh_post(f"repos/{GITHUB_REPO}/issues/{issue['number']}/comments", {"body": comment_body})

        consensus_label = f"consensus:{consensus}"
        _ensure_label(consensus_label, "c5def5")
        _gh_post(f"repos/{GITHUB_REPO}/issues/{issue['number']}/labels", {"labels": [consensus_label]})

        summary["stances_posted"] += 1

    summary["consensus_rescored"] = rescore_stale_consensus()
    return summary


def rescore_stale_consensus() -> int:
    """Re-derive consensus for already-stanced open proposals against the
    CURRENT agent_track_record, and refresh the consensus:X label when it
    moved. compute_consensus() only ever runs once, at first-review time —
    a label can sit stale below the 0.55 eligibility threshold indefinitely
    even after track-record accuracy climbs (#230/#192 both did, 2026-07-12).
    No new AI stance is generated; this only re-scores the stance already on
    record."""
    rescored = 0
    for issue in get_open_proposal_issues():
        labels = [l["name"] for l in issue.get("labels", [])]

        proposed_by = next(
            (m.group(1) for l in labels if (m := _PROPOSED_BY_LABEL_RE.match(l))), None
        )
        reviewer = _other_agent(proposed_by)
        if not reviewer:
            continue

        existing_consensus_labels = [
            (l, float(m.group(1))) for l in labels if (m := _CONSENSUS_LABEL_RE.match(l))
        ]
        if not existing_consensus_labels:
            continue  # no stance reviewed yet — run_debate_cycle()'s normal loop handles it

        comments = _gh_get(f"repos/{GITHUB_REPO}/issues/{issue['number']}/comments") or []
        stance_match = next(
            (
                m for c in comments
                if (m := _STANCE_COMMENT_RE.search(c.get("body", "")))
                and m.group(1) == reviewer
            ),
            None,
        )
        if not stance_match:
            continue

        stance = {"stance": stance_match.group(2), "confidence": float(stance_match.group(3))}
        body = issue.get("body", "") or ""
        impact_match = _IMPACT_RE.search(body)
        impact_score = float(impact_match.group(1)) if impact_match else 5.0

        new_consensus = compute_consensus(proposed_by, reviewer, impact_score, stance)
        old_consensus = max(v for _, v in existing_consensus_labels)
        if abs(new_consensus - old_consensus) <= _STALE_CONSENSUS_THRESHOLD:
            continue

        for label_name, _ in existing_consensus_labels:
            _gh_delete(f"repos/{GITHUB_REPO}/issues/{issue['number']}/labels/{label_name}")

        new_label = f"consensus:{new_consensus}"
        _ensure_label(new_label, "c5def5")
        _gh_post(f"repos/{GITHUB_REPO}/issues/{issue['number']}/labels", {"labels": [new_label]})
        rescored += 1

    return rescored


if __name__ == "__main__":
    print(run_debate_cycle())
