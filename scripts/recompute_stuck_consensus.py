#!/usr/bin/env python3
"""
recompute_stuck_consensus.py — one-time maintenance: re-derive the
consensus:X label on open agent-proposal issues that already carry a
genuine reviewer stance, using the current agent_track_record.

run_debate_cycle() only computes consensus once per issue (gated by
_already_reviewed_by()), at the moment the reviewing agent posts its
stance. Every proposal reviewed while agent_track_record still held
Claude's cold-start default (see record_proposal_outcome.py backfill,
2026-07-10) is stuck at that stale score forever -- it will never be
revisited since it already has a stance. This script re-reads each
issue's existing stance comment, recomputes compute_consensus() with
today's track record, and rewrites the label + posts a short note if
the score changed enough to matter (i.e. crossed the 0.55 eligibility
threshold).

Usage: python3 scripts/recompute_stuck_consensus.py
"""

from __future__ import annotations

import re

import requests

from community import _gh_get, _gh_post, _gh_headers, _GH_API, GITHUB_REPO
from github_sync import get_open_proposal_issues, _ensure_label
from debate import compute_consensus, _IMPACT_RE


def _gh_delete_label(issue_number: int, label: str) -> None:
    try:
        requests.delete(
            f"{_GH_API}/repos/{GITHUB_REPO}/issues/{issue_number}/labels/{label}",
            headers=_gh_headers(), timeout=15,
        )
    except Exception as e:
        print(f"  [GH] DELETE label error: {e}")

_STANCE_RE = re.compile(
    r"\*\*Stance \((claude|gemini)\):\*\*\s*(agree|disagree|escalate)\s*\(confidence\s*([\d.]+)\)"
)


def _latest_stance(comments: list) -> tuple[str, dict] | None:
    for c in reversed(comments):
        m = _STANCE_RE.search(c.get("body", ""))
        if m:
            reviewer, stance, confidence = m.groups()
            return reviewer, {"stance": stance, "confidence": float(confidence)}
    return None


def main():
    issues = get_open_proposal_issues()
    updated = []
    for issue in issues:
        labels = [l["name"] for l in issue.get("labels", [])]
        old_consensus_label = next((l for l in labels if l.startswith("consensus:")), None)
        if not old_consensus_label:
            continue
        proposed_by = next((l.split(":", 1)[1] for l in labels if l.startswith("proposed-by:")), None)
        if not proposed_by:
            continue

        comments = _gh_get(f"repos/{GITHUB_REPO}/issues/{issue['number']}/comments") or []
        found = _latest_stance(comments)
        if not found:
            continue
        reviewer, stance = found

        body = issue.get("body", "") or ""
        impact_match = _IMPACT_RE.search(body)
        impact_score = float(impact_match.group(1)) if impact_match else 5.0
        new_consensus = compute_consensus(proposed_by, reviewer, impact_score, stance)

        old_value = float(old_consensus_label.split(":", 1)[1])
        if abs(new_consensus - old_value) < 0.001:
            continue

        new_label = f"consensus:{new_consensus}"
        _ensure_label(new_label, "c5def5")
        _gh_post(
            f"repos/{GITHUB_REPO}/issues/{issue['number']}/labels",
            {"labels": [new_label]},
        )
        _gh_delete_label(issue["number"], old_consensus_label)
        note = (
            f"**Consensus recomputed:** {old_value} → {new_consensus} "
            f"(agent_track_record backfill corrected {proposed_by}'s accuracy from the "
            f"0.7 cold-start default to its real historical rate)."
        )
        _gh_post(f"repos/{GITHUB_REPO}/issues/{issue['number']}/comments", {"body": note})
        updated.append((issue["number"], old_value, new_consensus))
        print(f"#{issue['number']}: {old_value} -> {new_consensus}")

    if not updated:
        print("No consensus labels changed")


if __name__ == "__main__":
    main()
