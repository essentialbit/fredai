"""
Read-only audit for feature_backlog rows stuck at status='in_progress'.

reconcile_feature_backlog.py already catches the case where a row's own
linked GitHub issue was closed but the local status was never backfilled.
It does NOT catch the class documented in FinanceAgent memory (2026-08-02,
proposal ids 21/20/18): an in_progress row whose issue is still open with
no PR ever merged against it — orphaned by an interrupted session, a stale
duplicate of work that actually shipped under a *different* proposal, or
only partially shipped. Telling those three apart is a judgment call this
script deliberately does not make (see fredai.md's documented playbook for
the per-case reconciliation logic); it only surfaces the evidence — PRs
that actually claim to close the linked issue (verified via a closes/fixes/
resolves #N regex, not a raw timeline cross-reference — the timeline alone
false-positives on any PR/issue that merely mentions the number, confirmed
live against issue #103) plus row age — so a human or a future cycle can
pick the right action.

Never writes to feature_backlog. Never calls mark_proposal_done() or any
status-changing function.

Usage:
    PYTHONPATH=. python3 scripts/audit_stuck_in_progress.py
"""

import re
import sys
from datetime import datetime, timezone

from community import _gh_get, GITHUB_REPO, GITHUB_TOKEN
from memory_store import get_conn

_CLOSE_KEYWORDS = r'\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#{n}\b'


def _stuck_rows() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, category, proposed_by, github_issue_number, "
            "updated_at FROM feature_backlog WHERE status='in_progress'"
        ).fetchall()
    return [dict(r) for r in rows]


def _linked_prs(issue_number: int) -> list[dict]:
    """PRs that actually close this issue, verified via a closes/fixes/resolves
    #N regex on the PR body — not just any cross-referenced timeline entry.

    The issue timeline's cross-reference events include any PR/issue whose body
    merely mentions "#N" anywhere (confirmed live against issue #103: five
    unrelated merged PRs showed up as cross-referenced purely because sibling
    proposal issues used "distinct from #103" boilerplate disambiguation text —
    the same incidental-mention false-positive class already documented for
    text search in fredai.md). The regex check below is what actually verifies
    a PR claims to close *this* issue.
    """
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

    rows = _stuck_rows()
    if not rows:
        print("No rows at status='in_progress' — nothing to audit.")
        return 0

    print(f"Auditing {len(rows)} in_progress row(s).\n")

    for row in rows:
        age = _age_days(row["updated_at"])
        age_str = f"{age:.1f}d" if age >= 0 else "unknown age"
        print(f"id={row['id']} \"{row['title']}\" (proposed_by={row['proposed_by']}, "
              f"category={row['category']}, stuck {age_str})")

        if not row["github_issue_number"]:
            print("  -> no github_issue_number linked; cannot check for a real PR via the "
                  "issue timeline. Check git log / gh pr list by hand.")
            continue

        prs = _linked_prs(row["github_issue_number"])
        if not prs:
            print(f"  -> issue #{row['github_issue_number']}: NO cross-referenced PR found. "
                  "Orphan candidate — check fredai.md's stuck-in_progress playbook before "
                  "reverting (interrupted session vs. duplicate-of-different-PR vs. partial).")
        else:
            for pr in prs:
                status = "merged" if pr["merged"] else pr["state"]
                print(f"  -> issue #{row['github_issue_number']}: linked PR #{pr['number']} "
                      f"({status}) \"{pr['title']}\"")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
