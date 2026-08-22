"""
Read-only audit for feature_backlog rows already at status='implemented'.

reconcile_feature_backlog.py backfills the opposite drift (issue closed,
local status stale). audit_stuck_in_progress.py covers status='in_progress'
orphans. Neither catches the class documented in FinanceAgent memory
(#231/id-14, id=19): a row already marked 'implemented' -- which bumps
agent_track_record via mark_proposal_done() -- whose linked GitHub issue is
still OPEN with no merged PR ever closing it. That's exactly Gemini's
observed bogus-self-bump failure mode (direct sentinel.db writes, no
commit/PR ever made).

An open issue with no closing PR is not automatically bogus -- it can also
be a benign sync gap (shipped, nobody closed the issue) or shipped under a
different proposal/PR than the one linked. Telling those apart is the same
judgment call fredai.md's stuck-in_progress playbook already declines to
automate, so this script only surfaces evidence (linked-PR search via the
same closes/fixes/resolves #N regex as audit_stuck_in_progress.py, not a
raw timeline cross-reference -- that false-positives on any PR merely
mentioning the number, confirmed live against issue #103) plus row age.

Never writes to feature_backlog. Never touches agent_track_record. Never
calls mark_proposal_done() or any status-changing function.

Usage:
    PYTHONPATH=. python3 scripts/audit_implemented_claims.py
"""

import re
import sys
from datetime import datetime, timezone

from community import _gh_get, GITHUB_REPO, GITHUB_TOKEN
from memory_store import get_conn

# Same regex as audit_stuck_in_progress.py, same known gap: a comma-list
# body like "Closes #560, #562, #563." only matches the first number --
# the keyword isn't repeated before #562/#563. Confirmed live against PR
# #564 (id=63/64 below print "no cross-referenced PR at all" despite a
# real merged-eventually PR covering them). Flags a false positive here,
# never a false negative -- worth a human glance, not a bug in this script.
_CLOSE_KEYWORDS = r'\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#{n}\b'


def _implemented_rows() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, category, proposed_by, github_issue_number, "
            "updated_at FROM feature_backlog WHERE status='implemented'"
        ).fetchall()
    return [dict(r) for r in rows]


def _issue_state(issue_number: int) -> str | None:
    data = _gh_get(f"repos/{GITHUB_REPO}/issues/{issue_number}")
    if not data:
        return None
    return data.get("state")


def _linked_prs(issue_number: int) -> list[dict]:
    """PRs that actually claim to close this issue -- same regex-verified
    approach as audit_stuck_in_progress.py (see that script's docstring for
    why a raw timeline cross-reference alone isn't sufficient evidence)."""
    events = _gh_get(f"repos/{GITHUB_REPO}/issues/{issue_number}/timeline", {"per_page": 100})
    if not events:
        return []
    pattern = re.compile(_CLOSE_KEYWORDS.format(n=issue_number), re.IGNORECASE)
    prs = []
    for e in events:
        src = e.get("source", {}).get("issue") if e.get("event") == "cross-referenced" else None
        if not src or "pull_request" not in src:
            continue
        if not pattern.search(src.get("body") or ""):
            continue
        prs.append({
            "number": src["number"],
            "state": src["state"],
            "merged": src.get("pull_request", {}).get("merged_at") is not None,
            "title": src.get("title", ""),
        })
    return prs


def _age_days(updated_at: str) -> float:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(updated_at, fmt).replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        except ValueError:
            continue
    return -1.0


def main():
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set — cannot reach GitHub, aborting.")
        return 1

    rows = _implemented_rows()
    if not rows:
        print("No rows at status='implemented' — nothing to audit.")
        return 0

    print(f"Auditing {len(rows)} implemented row(s).\n")
    flagged = 0

    for row in rows:
        if not row["github_issue_number"]:
            print(f"id={row['id']} \"{row['title']}\" (proposed_by={row['proposed_by']}) "
                  "-> no github_issue_number linked; cannot verify via GitHub. Check git log by hand.")
            print()
            continue

        state = _issue_state(row["github_issue_number"])
        if state is None:
            print(f"id={row['id']} \"{row['title']}\" -> issue #{row['github_issue_number']} "
                  "not found (deleted/inaccessible?). Manual check needed.")
            print()
            continue
        if state == "closed":
            continue  # closed issue is the expected, verified shape -- nothing to flag

        prs = _linked_prs(row["github_issue_number"])
        merged_prs = [p for p in prs if p["merged"]]
        if merged_prs:
            continue  # open issue but a merged PR actually closes it -- benign sync gap, not bogus

        flagged += 1
        age = _age_days(row["updated_at"])
        age_str = f"{age:.1f}d" if age >= 0 else "unknown age"
        print(f"id={row['id']} \"{row['title']}\" (proposed_by={row['proposed_by']}, "
              f"category={row['category']}, marked implemented {age_str} ago)")
        print(f"  -> issue #{row['github_issue_number']} is still OPEN and no merged PR closes it.")
        if prs:
            for pr in prs:
                print(f"     candidate PR #{pr['number']} ({pr['state']}, not merged) \"{pr['title']}\"")
        else:
            print("     no cross-referenced PR at all.")
        print("     Unverified 'implemented' claim -- check fredai.md's Gemini-bogus-bump "
              "precedent (#231/id-14, id=19) before treating agent_track_record as trustworthy for this row.")
        print()

    print(f"{flagged} unverified 'implemented' row(s) out of {len(rows)} checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
