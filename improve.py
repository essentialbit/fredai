#!/usr/bin/env python3
"""
FredAI Self-Improvement Runner
================================
Called every 6h by the scheduler and GitHub Actions CI.
Runs a full cycle:
  1. Analyze current signal quality and coverage gaps
  2. Run R&D discovery (Claude researches what to build next)
  3. Implement top proposal via ClaudeCodeAgent (Fred ↔ Claude loop)
  4. Commit + push to GitHub
  5. Log everything to Obsidian vault

Usage:
  python3 improve.py              # Full cycle (includes Claude implementation)
  python3 improve.py --dry-run    # Analysis only, no code changes
  python3 improve.py --discover   # Discovery only, queue proposals, no implement
"""

import sys
import json
import subprocess
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory_store import init_db, get_signals, get_trending_assets, get_summaries, get_recent_alerts, get_all_proposals
from obsidian_bridge import write_improvement_log
from community import run_community_cycle


def analyze_current_state() -> dict:
    """Build a diagnostic report of Fred's current health."""
    signals_4h = get_signals(hours=4)
    signals_24h = get_signals(hours=24)
    trending = get_trending_assets(hours=4, limit=10)
    summaries = get_summaries(limit=3)
    alerts = get_recent_alerts(limit=20)
    proposals = get_all_proposals(limit=20)

    issues = []
    findings = []

    # Signal health
    if len(signals_4h) == 0:
        issues.append("ZERO signals last 4h — X API may be rate-limited or key invalid")
    elif len(signals_4h) < 15:
        issues.append(f"Low signal volume ({len(signals_4h)} in 4h) — consider expanding queries")

    if signals_4h:
        neutral_pct = sum(1 for s in signals_4h if s.get("signal_type") == "neutral") / len(signals_4h)
        if neutral_pct > 0.6:
            issues.append(f"High neutral rate ({neutral_pct:.0%}) — VADER undershooting financial sentiment")

    contents = [s.get("content","")[:80] for s in signals_4h]
    if contents:
        dupes = len(contents) - len(set(contents))
        if dupes > 2:
            issues.append(f"{dupes} duplicate signals — dedup needed")

    # AI health
    if not summaries:
        issues.append("No summaries — ANTHROPIC_API_KEY missing or invalid")
    else:
        findings.append(f"Last summary risk: {summaries[0].get('risk_level','?')}")

    # Coverage gaps
    covered = set(s.get("asset") for s in signals_24h if s.get("asset"))
    key_assets = {"AAPL","NVDA","TSLA","MSFT","BTC-USD","SPY","QQQ","ETH-USD"}
    uncovered = key_assets - covered
    if uncovered:
        issues.append(f"Zero signals for: {', '.join(sorted(uncovered))} in 24h")

    # Backlog status
    statuses = {}
    for p in proposals:
        s = p.get("status","?")
        statuses[s] = statuses.get(s, 0) + 1
    findings.append(f"Backlog: {statuses}")

    findings.append(f"Signals: {len(signals_4h)} (4h) | {len(signals_24h)} (24h)")
    findings.append(f"Trending: {[t['asset'] for t in trending[:5]]}")

    return {
        "issues": issues,
        "findings": findings,
        "signal_count_4h": len(signals_4h),
        "signal_count_24h": len(signals_24h),
        "has_summaries": bool(summaries),
        "covered_assets": list(covered),
    }


def git_push(message: str):
    try:
        root = Path(__file__).parent

        # Commit anything still sitting in the working tree. Note this can
        # legitimately be empty even when there's real work to push — the
        # code agents (claude_code_agent.py / gemini_code_agent.py) already
        # commit locally as they go via _auto_commit(), so by the time we
        # get here the tree may already be clean with commits still unpushed.
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=root).stdout.strip()
        if dirty:
            subprocess.run(["git", "add", "-A"], cwd=root)
            subprocess.run(["git", "commit", "-m", message], cwd=root)

        ahead = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"], capture_output=True, text=True, cwd=root
        ).stdout.strip()
        if ahead in ("", "0"):
            print("[Git] Nothing to push")
            return

        push = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, cwd=root)
        if push.returncode != 0:
            # Likely a non-fast-forward rejection from a concurrent cycle (Claude/Gemini/CI)
            # pushing in the same window — rebase onto the new remote tip and retry once.
            print(f"[Git] Push rejected, retrying after rebase: {push.stderr.strip()[:200]}")
            subprocess.run(["git", "fetch", "origin", "main"], cwd=root)
            rebase = subprocess.run(["git", "rebase", "origin/main"], capture_output=True, text=True, cwd=root)
            if rebase.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], cwd=root)
                print(f"[Git] Rebase failed, giving up this cycle: {rebase.stderr.strip()[:200]}")
                return
            retry = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, cwd=root)
            if retry.returncode != 0:
                print(f"[Git] Retry push failed: {retry.stderr.strip()[:200]}")
                return

        print(f"[Git] Pushed: {message}")
    except Exception as e:
        print(f"[Git] Error: {e}")


def run_improvement_cycle(dry_run: bool = False, discover_only: bool = False):
    print(f"\n{'='*64}")
    print(f"  FredAI Improvement Cycle — {datetime.now(UTC).isoformat()[:16]} UTC")
    if dry_run:
        print("  MODE: DRY RUN (no code changes)")
    elif discover_only:
        print("  MODE: DISCOVER ONLY (queue proposals, no implementation)")
    print(f"{'='*64}\n")

    init_db()

    # ── Phase 0: Community engagement ─────────────────────────────
    print("[Phase 0] Checking GitHub community interactions...")
    community_summary = {}
    try:
        community_summary = run_community_cycle()
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

    # ── FSI Mission banner ────────────────────────────────────────
    from pathlib import Path as _Path
    if (_Path(__file__).parent / "MISSION.md").exists():
        print("[FSI] North Star: World's First Financial Super Intelligence")
        print("[FSI] Current level: L1 complete → L2 Pattern Intelligence (active)")

    # ── Phase 1: Diagnose ──────────────────────────────────────────
    print("[Phase 1] Analyzing current state...")
    state = analyze_current_state()
    for issue in state["issues"]:
        print(f"  ⚠ {issue}")
    for finding in state["findings"]:
        print(f"  ✓ {finding}")

    if dry_run:
        print("\n[DRY RUN] Stopping before implementation.")
        return state

    # ── Phase 2: R&D Discovery ────────────────────────────────────
    print("\n[Phase 2] Running R&D discovery...")
    import anthropic
    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("  [SKIP] ANTHROPIC_API_KEY not set — skipping R&D")
        return state

    try:
        from fred_rnd import run_rnd_cycle
        rnd_results = run_rnd_cycle(implement=(not discover_only))
        print(f"  Discovered: {rnd_results.get('discovered', 0)} proposals")
        if rnd_results.get("implemented"):
            impl = rnd_results["implemented"]
            print(f"  Implemented: {impl['proposal']} (success={impl['success']})")
            print(f"  Files changed: {impl['files_changed']}")
    except Exception as e:
        print(f"  [RnD ERROR] {e}")
        import traceback; traceback.print_exc()
        rnd_results = {}

    # ── Phase 3: Commit & Push ────────────────────────────────────
    print("\n[Phase 3] Committing changes...")
    ts = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    impl_title = rnd_results.get("implemented", {}) or {}
    title = impl_title.get("proposal", "maintenance") if isinstance(impl_title, dict) else "maintenance"
    git_push(f"auto-improve({ts}): {title}")

    # ── Phase 4: Log to Obsidian ──────────────────────────────────
    report = "\n".join([
        "## Community",
        json.dumps(community_summary, indent=2, default=str),
        "",
        "## Diagnostics",
        *[f"- ⚠ {i}" for i in state["issues"]],
        *[f"- ✓ {f}" for f in state["findings"]],
        "",
        "## R&D Results",
        json.dumps(rnd_results, indent=2, default=str),
    ])
    write_improvement_log(f"Improvement cycle {ts}", report)

    print(f"\n{'='*64}")
    print(f"  Cycle complete. Next in 6h.")
    print(f"{'='*64}\n")
    return {**state, "rnd": rnd_results}


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    discover_only = "--discover" in sys.argv
    run_improvement_cycle(dry_run=dry_run, discover_only=discover_only)
