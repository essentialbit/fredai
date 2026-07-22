"""
Bulk-diff local feature_backlog rows against their matched GitHub Issue
state, so a proposal whose Issue was closed (shipped, merged, or declined)
doesn't sit forever at status='proposed'/'in_progress' locally.

This class of staleness previously required a manual audit (see FinanceAgent
memory: 2026-07-20 backfill of 15 stale rows after a DB restore) — this
script automates the read side of that audit. It never touches
agent_track_record and never calls mark_proposal_done() (that function has
no idempotency guard — see memory_store.py's own caveat); backfills go
through a direct SQL UPDATE instead, same as the manual precedent.

Only github_issue_number-linked rows are ever auto-applied. Unsynced rows
(no github_issue_number) are reported as possible title matches for manual
review only — a blind title match risks the same false-positive class as
the Jaccard proposal-dedup trap (#192/#174), so this script doesn't act on
it unprompted.

Usage:
    PYTHONPATH=. python3 scripts/reconcile_feature_backlog.py            # dry run
    PYTHONPATH=. python3 scripts/reconcile_feature_backlog.py --apply    # backfill confirmed matches
"""

import sys
from datetime import datetime, timezone

from community import _gh_get, GITHUB_REPO, GITHUB_TOKEN
from memory_store import get_conn


def _fetch_all_issues() -> dict[int, dict]:
    """number -> {title, state} for every issue (open + closed), PRs excluded."""
    issues = {}
    page = 1
    while True:
        data = _gh_get(f"repos/{GITHUB_REPO}/issues", {
            "state": "all", "per_page": 100, "page": page,
        })
        if not data:
            break
        for item in data:
            if "pull_request" in item:
                continue
            issues[item["number"]] = {"title": item["title"], "state": item["state"]}
        if len(data) < 100:
            break
        page += 1
    return issues


def _open_backlog_rows() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, status, github_issue_number FROM feature_backlog "
            "WHERE status IN ('proposed','in_progress')"
        ).fetchall()
    return [dict(r) for r in rows]


def _apply_backfill(proposal_id: int, issue_number: int):
    note = (
        f"auto-reconciled: GitHub issue #{issue_number} closed, backfilled by "
        f"reconcile_feature_backlog.py on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE feature_backlog SET status='implemented', implementation_notes=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (note, proposal_id),
        )


def main():
    apply = "--apply" in sys.argv

    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set — cannot reach GitHub, aborting.")
        return 1

    rows = _open_backlog_rows()
    if not rows:
        print("No local rows at status proposed/in_progress — nothing to reconcile.")
        return 0

    issues = _fetch_all_issues()

    confirmed = []   # linked via github_issue_number, issue closed
    possible = []    # unsynced, title matches a closed issue
    ok = []          # linked, issue still open — no action

    closed_titles = {
        v["title"].strip().lower(): num
        for num, v in issues.items() if v["state"] == "closed"
    }

    for row in rows:
        issue_num = row["github_issue_number"]
        if issue_num:
            issue = issues.get(issue_num)
            if issue and issue["state"] == "closed":
                confirmed.append((row, issue_num))
            else:
                ok.append(row)
            continue

        match_num = closed_titles.get((row["title"] or "").strip().lower())
        if match_num:
            possible.append((row, match_num))

    print(f"Checked {len(rows)} open local proposals against {len(issues)} GitHub issues.\n")

    print(f"Confirmed stale (github_issue_number linked + closed): {len(confirmed)}")
    for row, num in confirmed:
        print(f"  id={row['id']} \"{row['title']}\" -> issue #{num} (closed), local status={row['status']}")

    print(f"\nPossible stale (unsynced, exact title match to a closed issue): {len(possible)}")
    for row, num in possible:
        print(f"  id={row['id']} \"{row['title']}\" -> issue #{num} (closed) — NOT auto-applied, needs manual confirm")

    print(f"\nStill genuinely open (linked, issue open): {len(ok)}")

    if not confirmed:
        print("\nNothing to apply.")
        return 0

    if apply:
        for row, num in confirmed:
            _apply_backfill(row["id"], num)
        print(f"\nApplied: backfilled {len(confirmed)} row(s) to status='implemented'.")
    else:
        print(f"\nDry run — re-run with --apply to backfill the {len(confirmed)} confirmed row(s).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
