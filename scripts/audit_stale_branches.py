"""
Stale-branch audit — read-only survey of every non-default branch on
essentialbit/fredai.

This repo's fast-moving auto-improve workflow (one feature branch per PR,
many PRs/day at peak) has never had a script auditing whether merged-PR
branches actually got cleaned up, or whether any branch has commits that
were never shipped via any PR at all (the `agent/claude-20260712171340`
case flagged in memory as a manual one-off review item). This fills that
gap the same way `pr_merge_planner.py`/`reconcile_feature_backlog.py` do
for their own corners: cheap, read-only, JSON-out, no git/GitHub writes.

Buckets each non-default branch by how it relates to `main`:
  - active_open_pr        — has an open PR; leave alone.
  - merged_safe_to_delete — its PR merged; branch is pure history now,
                             safe for a human to delete.
  - closed_unmerged       — has a PR but it was closed without merging
                             (explicitly rejected/superseded) — review,
                             don't assume safe.
  - no_pr_no_unique_commits — never had a PR and carries no commits
                             absent from main (e.g. an old snapshot or a
                             branch created directly at main's tip) —
                             safe to delete.
  - no_pr_has_unique_commits — never had a PR AND carries commits not in
                             main — orphaned work, needs a human look
                             before any deletion (this is the risky
                             bucket; never auto-delete from this script).

Never deletes anything itself — deletion is a destructive action and
stays a human (or explicitly-authorized) decision.

Usage: PYTHONPATH=. python3 scripts/audit_stale_branches.py
Prints a JSON report to stdout.
"""

import json

from community import _gh_get, GITHUB_REPO

DEFAULT_BRANCH = "main"


def _get_all_branches() -> list[dict]:
    branches = []
    page = 1
    while True:
        batch = _gh_get(f"repos/{GITHUB_REPO}/branches", {
            "per_page": 100, "page": page,
        })
        if not batch:
            break
        branches.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return branches


def _get_all_prs_all_states() -> list[dict]:
    prs = []
    page = 1
    while True:
        batch = _gh_get(f"repos/{GITHUB_REPO}/pulls", {
            "state": "all", "per_page": 100, "page": page,
        })
        if not batch:
            break
        prs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return prs


def _compare_to_main(branch: str) -> dict | None:
    return _gh_get(f"repos/{GITHUB_REPO}/compare/{DEFAULT_BRANCH}...{branch}")


def audit() -> dict:
    branches = [b for b in _get_all_branches() if b["name"] != DEFAULT_BRANCH]
    prs = _get_all_prs_all_states()

    by_head: dict[str, list[dict]] = {}
    for pr in prs:
        head = pr.get("head", {}).get("ref")
        if head:
            by_head.setdefault(head, []).append(pr)

    buckets: dict[str, list[dict]] = {
        "active_open_pr": [],
        "merged_safe_to_delete": [],
        "closed_unmerged": [],
        "no_pr_no_unique_commits": [],
        "no_pr_has_unique_commits": [],
    }

    for b in branches:
        name = b["name"]
        commit = b.get("commit", {})
        entry = {
            "branch": name,
            "sha": commit.get("sha", "")[:12],
        }
        matching = by_head.get(name, [])

        if any(pr["state"] == "open" for pr in matching):
            open_pr = next(pr for pr in matching if pr["state"] == "open")
            entry["pr_number"] = open_pr["number"]
            buckets["active_open_pr"].append(entry)
            continue

        merged = [pr for pr in matching if pr.get("merged_at")]
        if merged:
            entry["pr_number"] = merged[0]["number"]
            entry["merged_at"] = merged[0]["merged_at"]
            buckets["merged_safe_to_delete"].append(entry)
            continue

        closed_unmerged = [pr for pr in matching if pr["state"] == "closed"]
        if closed_unmerged:
            entry["pr_number"] = closed_unmerged[0]["number"]
            entry["closed_at"] = closed_unmerged[0].get("closed_at")
            buckets["closed_unmerged"].append(entry)
            continue

        cmp = _compare_to_main(name)
        ahead_by = (cmp or {}).get("ahead_by", 0)
        entry["ahead_by"] = ahead_by
        if ahead_by == 0:
            buckets["no_pr_no_unique_commits"].append(entry)
        else:
            buckets["no_pr_has_unique_commits"].append(entry)

    return {
        "total_branches_checked": len(branches),
        "counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, default=str))
