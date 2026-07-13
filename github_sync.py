"""
FredAI Collaboration Board — Proposal <-> GitHub Issue Sync
=============================================================
GitHub Issues are the system of record for Claude/Gemini proposals: each
`feature_backlog` row gets a mirrored Issue, labeled with FSI level,
category, risk tier, and which agent proposed it. Reuses community.py's
existing GitHub REST client rather than standing up a second one.
"""

import re

from community import _gh_get, _gh_post, GITHUB_REPO, GITHUB_TOKEN
from risk_rules import classify_risk

_LABEL_COLORS = {
    "agent-proposal": "5319e7",
    "risk:high": "b60205",
    "risk:medium": "fbca04",
    "risk:low": "0e8a16",
    "proposed-by:claude": "d93f0b",
    "proposed-by:gemini": "1d76db",
}


def _fsi_level(description: str) -> str:
    m = re.match(r"\[FSI L(\d+)\]", description or "")
    return m.group(1) if m else "?"


def _ensure_label(name: str, color: str = "ededed"):
    # Idempotent — community.py's _gh_post already logs and returns None on
    # non-2xx (e.g. 422 "already exists"), which is exactly what we want here.
    _gh_post(f"repos/{GITHUB_REPO}/labels", {"name": name, "color": color})


def sync_proposal_to_issue(proposal: dict) -> int | None:
    """Mirror a feature_backlog row to a GitHub Issue. Returns the issue
    number, or None if GITHUB_TOKEN isn't configured or the request fails.

    Idempotent per proposal_id: insert_feature_proposal()'s dedup can return
    an *existing* row's id when a near-duplicate is proposed again, but that
    doesn't mean the issue-sync step should create a second Issue for it —
    check the DB for an already-linked issue number first."""
    if not GITHUB_TOKEN:
        return None

    from memory_store import get_proposal
    existing = get_proposal(proposal["id"])
    if existing and existing.get("github_issue_number"):
        return existing["github_issue_number"]

    fsi = _fsi_level(proposal.get("description", ""))
    risk = classify_risk(
        proposal.get("category", ""),
        proposal.get("description", ""),
        proposal.get("estimated_hours", 0) or 0,
    )
    agent = proposal.get("proposed_by", "rnd_cycle")

    labels = [
        "agent-proposal",
        f"fsi-l{fsi}",
        f"category:{proposal.get('category', 'general')}",
        f"risk:{risk}",
        f"proposed-by:{agent}",
    ]
    for label in labels:
        _ensure_label(label, _LABEL_COLORS.get(label, "ededed"))

    body = "\n".join([
        f"**FSI Level:** {fsi}",
        f"**Category:** {proposal.get('category', 'general')}",
        f"**Impact score:** {proposal.get('impact_score', '?')}",
        f"**Estimated hours:** {proposal.get('estimated_hours', '?')}",
        f"**Proposed by:** {agent}",
        "",
        "### Description",
        proposal.get("description", ""),
        "",
        "### Implementation spec",
        proposal.get("implementation_spec", "") or "_none provided_",
        "",
        f"<!--fredai:proposal_id={proposal['id']}-->",
    ])

    result = _gh_post(f"repos/{GITHUB_REPO}/issues", {
        "title": proposal["title"],
        "body": body,
        "labels": labels,
    })
    if not result:
        return None

    issue_number = result.get("number")
    if issue_number:
        from memory_store import set_github_issue_number
        set_github_issue_number(proposal["id"], issue_number)
    return issue_number


def get_open_proposal_issues() -> list[dict]:
    """Fetch open Issues labeled agent-proposal — the debate cycle's input."""
    data = _gh_get(f"repos/{GITHUB_REPO}/issues", {
        "labels": "agent-proposal", "state": "open", "per_page": 100,
    })
    if not data:
        return []
    # Issues endpoint also returns PRs; filter those out.
    return [i for i in data if "pull_request" not in i]
