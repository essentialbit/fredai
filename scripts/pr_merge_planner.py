"""
PR merge-order planner — read-only analysis of the open PR backlog.

Splits open PRs into mergeable vs conflicting using GitHub's own
async-computed `mergeable` field (only present on the single-PR REST
endpoint, not the list endpoint, so this fetches each PR individually).
Conflicting PRs are grouped by pairwise changed-file overlap so a human
reviewer can see *why* a cluster conflicts (e.g. all touching
templates/dashboard.html) without them collapsing into one unreadable
blob -- an earlier version of this script clustered by transitive file
overlap across the whole backlog and every PR ended up in one 68-PR
cluster because nearly everything touches main.py/dashboard.html
somewhere; restricting clustering to the already-small conflicting
subset avoids that.

Also flags duplicate PR pairs that reference the same "closes #N" issue
(checking both title and body). The regex excludes possessive prose like
"closes #100's neighbor gap" (a real false positive hit on PR #251's
body during this script's own testing) via a negative lookahead.

Makes no git or GitHub write calls; merges nothing itself.

Usage: PYTHONPATH=. python3 scripts/pr_merge_planner.py
Prints a JSON report to stdout.
"""

import json
import re

from community import _gh_get, GITHUB_REPO

_ISSUE_REF_RE = re.compile(r"closes?\s+#(\d+)(?!['’]s)", re.IGNORECASE)


def _get_open_prs() -> list[dict]:
    prs = []
    page = 1
    while True:
        batch = _gh_get(f"repos/{GITHUB_REPO}/pulls", {
            "state": "open", "per_page": 100, "page": page,
        })
        if not batch:
            break
        prs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return prs


def _get_pr_detail(number: int) -> dict | None:
    return _gh_get(f"repos/{GITHUB_REPO}/pulls/{number}")


def _get_pr_files(number: int) -> set[str]:
    files = []
    page = 1
    while True:
        batch = _gh_get(f"repos/{GITHUB_REPO}/pulls/{number}/files", {
            "per_page": 100, "page": page,
        })
        if not batch:
            break
        files.extend(f["filename"] for f in batch)
        if len(batch) < 100:
            break
        page += 1
    return set(files)


def _closed_issue_numbers(pr: dict) -> set[int]:
    text = (pr.get("title") or "") + " " + (pr.get("body") or "")
    return {int(m.group(1)) for m in _ISSUE_REF_RE.finditer(text)}


def _find_duplicate_pairs(prs: list[dict]) -> list[dict]:
    by_issue: dict[int, list[dict]] = {}
    for pr in prs:
        for issue_num in _closed_issue_numbers(pr):
            by_issue.setdefault(issue_num, []).append(pr)

    duplicates = []
    for issue_num, group in by_issue.items():
        if len(group) < 2:
            continue
        duplicates.append({
            "issue": issue_num,
            "prs": sorted(
                [{"number": p["number"], "title": p["title"]} for p in group],
                key=lambda p: p["number"],
            ),
        })
    return duplicates


def _group_conflicting_by_overlap(numbers: list[int], files_by_pr: dict[int, set[str]]) -> list[dict]:
    """Pairwise (non-transitive) grouping: for each conflicting PR, list which
    other conflicting PRs it shares changed files with, and which files."""
    groups = []
    seen_pairs = set()
    for i, a in enumerate(numbers):
        for b in numbers[i + 1:]:
            shared = files_by_pr[a] & files_by_pr[b]
            if shared and (a, b) not in seen_pairs:
                seen_pairs.add((a, b))
                groups.append({"prs": [a, b], "shared_files": sorted(shared)})
    return groups


def build_merge_plan() -> dict:
    prs = _get_open_prs()
    details = {pr["number"]: _get_pr_detail(pr["number"]) for pr in prs}

    mergeable_prs, conflicting_prs, unknown_prs = [], [], []
    for pr in prs:
        detail = details.get(pr["number"]) or {}
        state = detail.get("mergeable")
        entry = {"number": pr["number"], "title": pr["title"], "created_at": pr["created_at"]}
        if state is True:
            mergeable_prs.append(entry)
        elif state is False:
            conflicting_prs.append(entry)
        else:
            unknown_prs.append(entry)

    mergeable_prs.sort(key=lambda p: p["created_at"])
    conflicting_prs.sort(key=lambda p: p["created_at"])

    conflicting_numbers = [p["number"] for p in conflicting_prs]
    files_by_pr = {n: _get_pr_files(n) for n in conflicting_numbers}
    overlap_groups = _group_conflicting_by_overlap(conflicting_numbers, files_by_pr)

    duplicates = _find_duplicate_pairs(prs)

    return {
        "total_open_prs": len(prs),
        "mergeable_first": mergeable_prs,
        "conflicting_needs_review": conflicting_prs,
        "conflicting_file_overlap_pairs": overlap_groups,
        "mergeable_state_unknown": unknown_prs,
        "duplicate_pairs": duplicates,
    }


if __name__ == "__main__":
    print(json.dumps(build_merge_plan(), indent=2))
