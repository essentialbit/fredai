"""
Truly-eligible backlog cross-reference — automates a check that had been
hand-rewritten in the sensor cycle's own reasoning for 3+ cycles running.

An open `agent-proposal` issue is only actually implementable if:
  - its highest posted `consensus:X` label is >= the eligibility threshold
  - it isn't `risk:high`
  - no pull request (open, merged, or closed) already references it via
    #N in EITHER the title OR the body — checking only one field produced
    a false ~10-issue "gap" once (title-only closes-#N links were missed).

Usage: PYTHONPATH=. python3 scripts/eligible_backlog.py [--threshold 0.55]
Prints the truly-eligible backlog as JSON to stdout.
"""

import argparse
import json
import re

from community import _gh_get, GITHUB_REPO

_ISSUE_REF_RE = re.compile(r"#(\d+)")


def _get_open_proposals() -> list[dict]:
    data = _gh_get(f"repos/{GITHUB_REPO}/issues", {
        "labels": "agent-proposal", "state": "open", "per_page": 100,
    })
    if not data:
        return []
    return [i for i in data if "pull_request" not in i]


def _get_all_prs() -> list[dict]:
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


def _referenced_issue_numbers(prs: list[dict]) -> set[int]:
    referenced = set()
    for pr in prs:
        text = (pr.get("title") or "") + " " + (pr.get("body") or "")
        for m in _ISSUE_REF_RE.finditer(text):
            referenced.add(int(m.group(1)))
    return referenced


def compute_eligible_backlog(threshold: float = 0.55, stats: dict | None = None) -> list[dict]:
    issues = _get_open_proposals()
    referenced = _referenced_issue_numbers(_get_all_prs())

    if stats is not None:
        stats["total_open_proposals"] = len(issues)
        stats["excluded_risk_high"] = 0
        stats["excluded_below_threshold"] = 0
        stats["excluded_already_referenced"] = 0
        stats["max_consensus_seen"] = 0.0

    eligible = []
    for issue in issues:
        labels = [l["name"] for l in issue.get("labels", [])]
        if "risk:high" in labels:
            if stats is not None:
                stats["excluded_risk_high"] += 1
            continue
        consensus_vals = [
            float(l.split(":", 1)[1]) for l in labels if l.startswith("consensus:")
        ]
        max_consensus = max(consensus_vals) if consensus_vals else 0.0
        if stats is not None:
            stats["max_consensus_seen"] = max(stats["max_consensus_seen"], max_consensus)
        if max_consensus < threshold:
            if stats is not None:
                stats["excluded_below_threshold"] += 1
            continue
        if issue["number"] in referenced:
            if stats is not None:
                stats["excluded_already_referenced"] += 1
            continue
        eligible.append({
            "number": issue["number"],
            "title": issue["title"],
            "consensus": max_consensus,
            "labels": labels,
        })
    return eligible


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument(
        "--stats", action="store_true",
        help="Print an exclusion-reason breakdown to stderr (stdout JSON unchanged) "
             "so an empty result is distinguishable from a silent query failure.",
    )
    args = parser.parse_args()
    stats_dict: dict = {} if args.stats else None
    result = compute_eligible_backlog(args.threshold, stats=stats_dict)
    if args.stats:
        print(json.dumps(stats_dict, indent=2), file=sys.stderr)
    print(json.dumps(result, indent=2))
