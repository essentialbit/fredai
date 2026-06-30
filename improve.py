#!/usr/bin/env python3
"""
FredAI Self-Improvement Runner — invoked by Claude Code every 6h via cron.
Analyzes signal quality, identifies gaps, researches improvements,
and commits enhancements to the codebase.

Usage:
  python3 improve.py [--dry-run]
"""
import sys
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from memory_store import init_db, get_signals, get_trending_assets, get_summaries, get_recent_alerts
from obsidian_bridge import write_improvement_log


def run_improvement_cycle(dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  FredAI Self-Improvement Cycle — {datetime.utcnow().isoformat()[:16]} UTC")
    print(f"{'='*60}\n")

    init_db()
    report = []

    # ── 1. ANALYZE SIGNAL QUALITY ─────────────────────────────────
    signals_4h = get_signals(hours=4)
    signals_24h = get_signals(hours=24)
    trending = get_trending_assets(hours=4)

    report.append(f"Signal volume: {len(signals_4h)} (4h) | {len(signals_24h)} (24h)")

    # Identify uncovered assets (check if top trending have good signal density)
    if len(signals_4h) == 0:
        report.append("⚠ ZERO signals in last 4h — X API may be rate limited or misconfigured")
    elif len(signals_4h) < 10:
        report.append(f"⚠ Low signal volume ({len(signals_4h)}) — consider expanding search queries")

    # Check for duplicate detection
    contents = [s.get("content", "")[:80] for s in signals_4h]
    unique = len(set(contents))
    if len(contents) > 0 and unique / len(contents) < 0.8:
        report.append(f"⚠ Duplicate signals detected ({len(contents) - unique} dupes) — dedup needed")

    # ── 2. IDENTIFY HIGH-VALUE OPPORTUNITIES ──────────────────────
    alerts = get_recent_alerts(limit=20)
    unack = [a for a in alerts if not a.get("acknowledged")]
    report.append(f"Active alerts: {len(unack)} unacknowledged")

    # Check summaries exist
    summaries = get_summaries(limit=3)
    if not summaries:
        report.append("⚠ No summaries generated yet — Anthropic API key may be missing")
    else:
        report.append(f"Last summary risk level: {summaries[0].get('risk_level', 'unknown')}")

    # ── 3. GENERATE IMPROVEMENT PROPOSALS ─────────────────────────
    proposals = generate_proposals(signals_4h, trending, report)
    report.append(f"\nProposals generated: {len(proposals)}")
    for p in proposals:
        report.append(f"  → {p}")

    # ── 4. LOG TO OBSIDIAN ────────────────────────────────────────
    summary = "\n".join(report)
    print(summary)

    if not dry_run:
        write_improvement_log(
            what=f"Improvement cycle at {datetime.utcnow().isoformat()[:16]}",
            details=summary + "\n\n## Proposals\n" + "\n".join(f"- {p}" for p in proposals)
        )

        # ── 5. AUTO-COMMIT IF CODE CHANGED ────────────────────────
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True,
                cwd=Path(__file__).parent
            )
            if result.stdout.strip():
                subprocess.run(["git", "add", "-A"], cwd=Path(__file__).parent)
                msg = f"auto-improve: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} — {proposals[0] if proposals else 'maintenance'}"
                subprocess.run(["git", "commit", "-m", msg], cwd=Path(__file__).parent)
                subprocess.run(["git", "push", "origin", "main"], cwd=Path(__file__).parent)
                print(f"\n[Git] Committed and pushed: {msg}")
            else:
                print("\n[Git] No code changes to commit.")
        except Exception as e:
            print(f"\n[Git] Commit failed: {e}")

    print(f"\n{'='*60}")
    print(f"  Cycle complete. Next run in 6h.")
    print(f"{'='*60}\n")
    return proposals


def generate_proposals(signals: list, trending: list, report: list) -> list[str]:
    """Analyze current state and generate actionable improvement proposals."""
    proposals = []

    # Signal volume proposals
    if len(signals) < 20:
        proposals.append("Expand X search queries to include macro keywords (CPI, NFP, FOMC)")

    # Coverage gap analysis
    covered_assets = set(s.get("asset") for s in signals if s.get("asset"))
    key_assets = {"AAPL", "NVDA", "TSLA", "MSFT", "BTC-USD", "ETH-USD", "SPY", "QQQ"}
    uncovered = key_assets - covered_assets
    if uncovered:
        proposals.append(f"Add targeted queries for uncovered assets: {', '.join(sorted(uncovered))}")

    # Sentiment quality
    neutral_pct = sum(1 for s in signals if s.get("signal_type") == "neutral") / max(len(signals), 1)
    if neutral_pct > 0.6:
        proposals.append("High neutral signal ratio — consider financial-domain sentiment model (FinBERT)")

    # Dashboard proposals (research-driven, implement next cycle)
    proposals.extend([
        "Add options flow data (unusual activity) via public API",
        "Implement Fear & Greed Index widget (CNN Money API)",
        "Add RSI / MACD technical indicators overlay to price chart",
        "Implement portfolio correlation heatmap (assets vs each other)",
        "Add earnings calendar widget for next 7 days",
    ])

    return proposals[:8]


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run_improvement_cycle(dry_run=dry_run)
