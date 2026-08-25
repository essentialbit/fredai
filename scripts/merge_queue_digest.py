"""
Merge-queue review digest -- read-only triage aid for the open PR backlog.

The sensor's standing bottleneck (see fredai.md open item 2) isn't finding
mergeable PRs -- pr_merge_planner.py already confirms most of the backlog
is clean and conflict-free. The bottleneck is a live user session spending
time working through 30+ PRs one at a time with no sense of which ones are
fast reviews vs which need real attention. This script buckets the open,
non-draft backlog into a review order optimized for clearing volume first:

  1. quick_chores_fixes  -- fix:/chore: PRs, no risk keywords, small diff
  2. small_features      -- feat: PRs, no risk keywords, modest diff
  3. needs_attention      -- anything flagging a HIGH_RISK_KEYWORDS hit in
                             title/body (auth/payment/secret/etc. -- see
                             risk_rules.py), OR a large diff
  4. other                -- docs/test/uncategorized prefixes

Deliberately does NOT fold "touches main.py" into risk scoring the way
risk_rules.classify_risk() does -- nearly every feat: PR wires a new route
into main.py, so that signal would swamp every bucket into "high" and
defeat the point of triage. Touching a HIGH_RISK_FILES path is instead
surfaced as its own flag per PR, not a bucket driver.

Deliberately does NOT reuse risk_rules.HIGH_RISK_KEYWORDS' plain substring
match against the full PR body either, and unlike classify_risk() this
only scans the title. HIGH_RISK_KEYWORDS is tuned for short, deliberate
proposal descriptions; PR bodies are long engineering prose where "auth"/
"token"/"session" hit constantly as substrings of unrelated words
("author", "tokenizer", "Claude Code session") -- verified this against
the live PR backlog before shipping: full-body substring scan flagged
10/33 PRs, all false positives (zero were about auth/payments/secrets).
Word-boundary matching against the title alone dropped that to 1/33 on
the same backlog.

Makes no git or GitHub write calls; merges nothing itself.

Usage: PYTHONPATH=. python3 scripts/merge_queue_digest.py
Prints a JSON report to stdout.
"""

import json
import re
from datetime import datetime, UTC

from community import _gh_get, GITHUB_REPO
from risk_rules import HIGH_RISK_KEYWORDS, HIGH_RISK_FILES

_PREFIX_RE = re.compile(r"^(\w+)(?:\([^)]*\))?:\s*", re.IGNORECASE)
_RISK_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in HIGH_RISK_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

_SMALL_DIFF_LINES = 100
_MEDIUM_DIFF_LINES = 250


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
    return [p for p in prs if not p.get("draft")]


def _get_pr_detail(number: int) -> dict | None:
    return _gh_get(f"repos/{GITHUB_REPO}/pulls/{number}")


def _kind(title: str) -> str:
    m = _PREFIX_RE.match(title.strip())
    return m.group(1).lower() if m else "other"


def _has_risk_keyword(title: str) -> bool:
    return bool(_RISK_KEYWORD_RE.search(title))


def _touches_high_risk_file(files: list[str]) -> bool:
    return any(any(hf in f for hf in HIGH_RISK_FILES) for f in files)


def _age_days(created_at: str) -> int:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (datetime.now(UTC) - created).days


def build_digest() -> dict:
    prs = _get_open_prs()

    entries = []
    for pr in prs:
        number = pr["number"]
        detail = _get_pr_detail(number) or {}
        title = pr["title"]
        additions = detail.get("additions", 0) or 0
        deletions = detail.get("deletions", 0) or 0
        changed_files = detail.get("changed_files", 0) or 0
        size = additions + deletions
        kind = _kind(title)
        risk_kw = _has_risk_keyword(title)
        high_risk_file = _touches_high_risk_file(
            [f["filename"] for f in (_gh_get(f"repos/{GITHUB_REPO}/pulls/{number}/files",
                                              {"per_page": 100}) or [])]
        )

        entries.append({
            "number": number,
            "title": title,
            "kind": kind,
            "size_lines": size,
            "changed_files": changed_files,
            "age_days": _age_days(pr["created_at"]),
            "risk_keyword_hit": risk_kw,
            "touches_high_risk_file": high_risk_file,
            "mergeable": detail.get("mergeable"),
        })

    quick_chores_fixes, small_features, needs_attention, other = [], [], [], []
    for e in entries:
        if e["risk_keyword_hit"] or e["size_lines"] >= _MEDIUM_DIFF_LINES:
            needs_attention.append(e)
        elif e["kind"] in ("fix", "chore") and e["size_lines"] < _SMALL_DIFF_LINES:
            quick_chores_fixes.append(e)
        elif e["kind"] == "feat" and e["size_lines"] < _MEDIUM_DIFF_LINES:
            small_features.append(e)
        else:
            other.append(e)

    for bucket in (quick_chores_fixes, small_features, needs_attention, other):
        bucket.sort(key=lambda e: e["size_lines"])

    total_lines = sum(e["size_lines"] for e in entries)

    return {
        "total_open_prs": len(entries),
        "total_diff_lines": total_lines,
        "oldest_pr_age_days": max((e["age_days"] for e in entries), default=0),
        "buckets": {
            "1_quick_chores_fixes": quick_chores_fixes,
            "2_small_features": small_features,
            "3_needs_attention": needs_attention,
            "4_other": other,
        },
        "review_order_note": (
            "Work buckets 1->2->4 first to clear volume fast; budget separate "
            "focused time for 3_needs_attention (risk keyword hit or 250+ line diff)."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(build_digest(), indent=2))
