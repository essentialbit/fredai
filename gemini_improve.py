#!/usr/bin/env python3
"""
FredAI Gemini Self-Improvement Runner
=====================================
Coordinates the Gemini-driven R&D discovery, code changes, and community engagement.
"""

import sys
import json
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory_store import init_db
from obsidian_bridge import write_improvement_log
from gemini_community import run_gemini_community_cycle
from gemini_rnd import run_gemini_rnd_cycle
from improve import analyze_current_state, git_push

def run_gemini_improvement_cycle(dry_run: bool = False, discover_only: bool = False):
    print(f"\n{'='*64}")
    print(f"  FredAI Gemini Improvement Cycle — {datetime.now(UTC).isoformat()[:16]} UTC")
    if dry_run:
        print("  MODE: DRY RUN (no code changes)")
    elif discover_only:
        print("  MODE: DISCOVER ONLY (queue proposals, no implementation)")
    print(f"{'='*64}\n")

    init_db()

    # ── Phase 0: Community engagement ─────────────────────────────
    print("[Phase 0] Checking GitHub community interactions (Gemini)...")
    community_summary = {}
    try:
        community_summary = run_gemini_community_cycle()
        print(f"  Issues: {community_summary.get('issues_checked', 0)} checked | "
              f"Discussions: {community_summary.get('discussions_checked', 0)} | "
              f"PRs: {community_summary.get('prs_checked', 0)} | "
              f"Responses posted: {community_summary.get('responses_posted', 0)}")
    except Exception as e:
        print(f"  [Community] Error: {e}")
        community_summary = {"error": str(e)}

    if dry_run:
        print("\n[DRY RUN] Stopping before implementation.")
        return {"community": community_summary}

    # ── Phase 1: Diagnose ──────────────────────────────────────────
    print("[Phase 1] Analyzing current state...")
    state = analyze_current_state()
    for issue in state["issues"]:
        print(f"  ⚠ {issue}")
    for finding in state["findings"]:
        print(f"  ✓ {finding}")

    # ── Phase 2: R&D Discovery & Implementation ────────────────────
    print("\n[Phase 2] Running Gemini R&D discovery...")
    rnd_results = {}
    try:
        rnd_results = run_gemini_rnd_cycle(implement=(not discover_only))
        print(f"  Discovered: {rnd_results.get('discovered', 0)} proposals")
        if rnd_results.get("implemented"):
            impl = rnd_results["implemented"]
            print(f"  Implemented: {impl['proposal']} (success={impl['success']})")
            print(f"  Files changed: {impl['files_changed']}")
    except Exception as e:
        print(f"  [RnD ERROR] {e}")
        import traceback; traceback.print_exc()

    # ── Phase 3: Commit & Push ────────────────────────────────────
    print("\n[Phase 3] Committing changes...")
    ts = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    impl_title = rnd_results.get("implemented", {}) or {}
    title = impl_title.get("proposal", "maintenance") if isinstance(impl_title, dict) else "maintenance"
    git_push(f"auto-improve-gemini({ts}): {title}")

    # ── Phase 4: Log to Obsidian ──────────────────────────────────
    report = "\n".join([
        "## Community (Gemini)",
        json.dumps(community_summary, indent=2, default=str),
        "",
        "## Diagnostics",
        *[f"- ⚠ {i}" for i in state["issues"]],
        *[f"- ✓ {f}" for f in state["findings"]],
        "",
        "## R&D Results (Gemini)",
        json.dumps(rnd_results, indent=2, default=str),
    ])
    write_improvement_log(f"Gemini Improvement cycle {ts}", report)

    print(f"\n{'='*64}")
    print(f"  Gemini Cycle complete. Next in 6h.")
    print(f"{'='*64}\n")
    return {**state, "rnd": rnd_results}

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    discover_only = "--discover" in sys.argv
    run_gemini_improvement_cycle(dry_run=dry_run, discover_only=discover_only)
