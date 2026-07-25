#!/usr/bin/env python3
"""
record_proposal_outcome.py — record a feature_backlog proposal's real-world
outcome (implemented via PR / abandoned) against its GitHub issue number.

fred_rnd.py and gemini_rnd.py already call memory_store.mark_proposal_done()
at the end of their own autonomous implementation loops, which also bumps
agent_track_record (debate.py's compute_consensus() reads that record to
weight an agent's proposals above the 0.7 cold-start default once it has
5+ tracked outcomes). The headless sensor's own "implement ONE item" cycle
picks a proposal and opens a PR by hand instead of calling that loop, so it
was silently never recording anything — agent_track_record stayed at its
cold-start default for every proposal the sensor itself implemented, capping
consensus scores well under the 0.55 eligibility threshold indefinitely.

Usage:
    python3 scripts/record_proposal_outcome.py <github_issue_number> <success|failure> [notes]

Example (after opening a PR for the proposal mirrored to issue #166):
    python3 scripts/record_proposal_outcome.py 166 success "PR #169"
"""

from __future__ import annotations

import sys

from memory_store import (
    get_proposal_by_issue_number,
    mark_proposal_in_progress,
    mark_proposal_done,
)


def record(issue_number: int, success: bool, notes: str = "") -> bool:
    proposal = get_proposal_by_issue_number(issue_number)
    if not proposal:
        print(f"No feature_backlog row linked to issue #{issue_number} -- nothing to record")
        return False
    mark_proposal_in_progress(proposal["id"])
    mark_proposal_done(proposal["id"], success=success, notes=notes)
    print(f"Recorded issue #{issue_number} (proposal id {proposal['id']}) as "
          f"{'success' if success else 'failure'}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[2] not in ("success", "failure"):
        print(__doc__)
        sys.exit(1)
    record(int(sys.argv[1]), sys.argv[2] == "success", sys.argv[3] if len(sys.argv) > 3 else "")
