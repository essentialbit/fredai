"""
Duplicate-issue auditor — read-only pairwise scan of ALL open GitHub issues.

`memory_store._find_similar_proposal()` only guards against a duplicate at
proposal-*insert* time, and only against local `feature_backlog` rows with
status in ('proposed', 'in_progress') filtered to the same category. It
never re-scans issues that already slipped through (dedup was fixed twice,
PR #544; issue #543 duplicating #484 predates that fix), issues filed by
hand outside `insert_feature_proposal()`, or issues whose local row moved to
a different status. This script closes that gap: it Jaccard-scores every
open issue's title+body against every other open issue, independent of
local DB state, using the same tokenizer as the proposal-time dedup
(`memory_store._tokenize`) plus a local stopword list stripping the issue
body template's own boilerplate ("**FSI Level:**", "### Description", ...)
and the near-universal "badge (FRED ...)" title convention, both confirmed
to otherwise inflate unrelated pairs to 0.3-0.4 -- the same class of
false-positive already documented for template-wrapped body comparisons.

Makes no GitHub write calls and closes nothing itself -- output is a
prioritized list for a human (or a future auto-close pass) to review.

Usage: PYTHONPATH=. python3 scripts/audit_duplicate_issues.py [--threshold 0.3]
Prints a JSON report to stdout.
"""
import argparse
import json
import re

from community import _gh_get, GITHUB_REPO
from memory_store import _tokenize

DEFAULT_THRESHOLD = 0.3

# github_sync.sync_proposal_to_issue()'s body template ("**FSI Level:**
# unknown", "### Description", "### Implementation spec", ...) and the
# "<name> badge (FRED <series>)" title convention both inject words shared
# by nearly every proposal regardless of subject -- confirmed inflating
# unrelated badge pairs to 0.34-0.42 (e.g. "10Y Term Premium" vs "Housing
# Affordability") before this list was added. Same class of false-positive
# already documented for gh-issue-body-vs-DB-description comparisons.
_TEMPLATE_STOPWORDS = {
    "fsi", "level", "category", "impact", "score", "estimated", "hours",
    "proposed", "description", "implementation", "spec", "none", "provided",
    "unknown", "general", "badge", "fred", "agent", "proposal",
}


def _content_tokens(text: str) -> set[str]:
    return _tokenize(text) - _TEMPLATE_STOPWORDS


def _get_open_issues() -> list[dict]:
    issues = []
    page = 1
    while True:
        batch = _gh_get(f"repos/{GITHUB_REPO}/issues", {
            "state": "open", "per_page": 100, "page": page,
        })
        if not batch:
            break
        # The issues endpoint also returns PRs; exclude those.
        issues.extend(i for i in batch if "pull_request" not in i)
        if len(batch) < 100:
            break
        page += 1
    return issues


def find_duplicate_pairs(issues: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    tokenized = [
        (issue, _content_tokens(issue.get("title", "")) | _content_tokens(issue.get("body", "")))
        for issue in issues
    ]
    pairs = []
    for i in range(len(tokenized)):
        issue_a, tokens_a = tokenized[i]
        if not tokens_a:
            continue
        for j in range(i + 1, len(tokenized)):
            issue_b, tokens_b = tokenized[j]
            if not tokens_b:
                continue
            overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
            if overlap >= threshold:
                pairs.append({
                    "score": round(overlap, 3),
                    "issue_a": issue_a["number"],
                    "title_a": issue_a["title"],
                    "issue_b": issue_b["number"],
                    "title_b": issue_b["title"],
                })
    pairs.sort(key=lambda p: p["score"], reverse=True)
    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    issues = _get_open_issues()
    pairs = find_duplicate_pairs(issues, args.threshold)
    print(json.dumps({
        "open_issues_scanned": len(issues),
        "threshold": args.threshold,
        "likely_duplicate_pairs": pairs,
    }, indent=2))


if __name__ == "__main__":
    main()
