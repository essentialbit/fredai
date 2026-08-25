"""
Stale PR branch updater — keeps open, non-conflicting PRs from rotting
into CONFLICTING as `main` moves ahead of them.

Every open PR whose REST `mergeable_state` is exactly "behind" (base has
new commits, but the PR's own diff still applies cleanly — the same
condition GitHub's PR-page "Update branch" button targets) gets that
merge-latest-base-into-branch operation triggered via the GitHub API.
This is a merge INTO the PR's own head branch, never into `main`, and
never merges the PR itself — it is the single riskiest-looking action
this script takes, and it is exactly as safe as a human clicking
"Update branch" on the PR page.

Deliberately conservative: only "behind" is touched. "dirty"/"blocked"/
"unstable"/"unknown"/draft PRs are left untouched and reported, not
retried — a PR that's actually CONFLICTING needs a real semantic
rebase (see fredai.md's documented resolution pattern), not a blind
API call that would just 422.

Motivated by the repeated multi-PR CONFLICTING-cluster rebase sessions
documented in project memory (e.g. 18/18 PRs in one sitting,
2026-07-21) -- a PR sitting BEHIND for even a few cycles is one merge
away from joining that pile. Running this every sensor cycle should
shrink how often that pile forms in the first place.

Makes no git-local changes and never touches `main`. Merges nothing.

Usage: PYTHONPATH=. python3 scripts/update_stale_pr_branches.py
Prints a JSON report to stdout.
"""

import json

import requests

from community import _gh_get, _gh_headers, _GH_API, _TIMEOUT, GITHUB_REPO


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


def _update_branch(number: int) -> tuple[bool, str]:
    try:
        r = requests.put(
            f"{_GH_API}/repos/{GITHUB_REPO}/pulls/{number}/update-branch",
            headers=_gh_headers(), timeout=_TIMEOUT,
        )
        if r.status_code == 202:
            return True, "accepted"
        return False, f"{r.status_code}: {r.text[:160]}"
    except Exception as e:
        return False, str(e)


def update_stale_branches(dry_run: bool = False) -> dict:
    prs = _get_open_prs()

    updated, skipped_not_behind, skipped_draft, errors = [], [], [], []

    for pr in prs:
        number = pr["number"]
        if pr.get("draft"):
            skipped_draft.append({"number": number, "title": pr["title"]})
            continue

        detail = _get_pr_detail(number) or {}
        state = detail.get("mergeable_state")
        entry = {"number": number, "title": pr["title"], "mergeable_state": state}

        if state != "behind":
            skipped_not_behind.append(entry)
            continue

        if dry_run:
            updated.append(entry)
            continue

        ok, detail_msg = _update_branch(number)
        entry["result"] = detail_msg
        if ok:
            updated.append(entry)
        else:
            errors.append(entry)

    return {
        "total_open_prs": len(prs),
        "updated": updated,
        "skipped_not_behind": skipped_not_behind,
        "skipped_draft": skipped_draft,
        "errors": errors,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(update_stale_branches(dry_run="--dry-run" in sys.argv), indent=2))
