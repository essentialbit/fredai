"""Bridge between FredAI and the Obsidian vault for persistent logging."""
import os
from datetime import datetime
from pathlib import Path

VAULT = Path("/Volumes/Iron 1TBSSD/Shared/Obsidian Vault")
FREDAI_DIR = VAULT / "AI" / "SMC" / "FredAI"
SIGNAL_DIR = FREDAI_DIR / "signals"
IMPROVE_DIR = FREDAI_DIR / "improvements"
SUMMARY_DIR = FREDAI_DIR / "summaries"
ACTIVE_CTX = VAULT / "AI" / "Shared" / "ActiveContext.md"


def vault_available() -> bool:
    return VAULT.exists()


def ensure_dirs():
    for d in [SIGNAL_DIR, IMPROVE_DIR, SUMMARY_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def write_summary_to_vault(content: str, period_label: str, stats: dict, risk: str):
    """Mirror a 4h summary to the Obsidian vault."""
    if not vault_available():
        return
    ensure_dirs()
    now = datetime.utcnow()
    fname = now.strftime("%Y-%m-%d-%H%M") + "-summary.md"
    fpath = SUMMARY_DIR / fname
    text = f"""---
date: {now.isoformat()}
period: {period_label}
risk: {risk}
sentiment_avg: {stats.get('avg', 0):.4f}
bullish_pct: {stats.get('bullish_pct', 0):.1f}
signal_count: {stats.get('count', 0)}
tags:
  - fredai
  - financial-summary
---

# FredAI 4h Briefing — {now.strftime('%Y-%m-%d %H:%M UTC')}

**Risk Level:** {risk} | **Bullish:** {stats.get('bullish_pct',0):.1f}% | **Signals:** {stats.get('count',0)}

{content}
"""
    fpath.write_text(text)
    _update_active_context(f"FredAI completed 4h scan — Risk: {risk}, {stats.get('count',0)} signals")


def write_improvement_log(what: str, details: str):
    """Log a self-improvement cycle to Obsidian."""
    if not vault_available():
        return
    ensure_dirs()
    now = datetime.utcnow()
    fname = now.strftime("%Y-%m-%d-%H%M") + "-improve.md"
    fpath = IMPROVE_DIR / fname
    text = f"""---
date: {now.isoformat()}
type: self-improvement
tags:
  - fredai
  - improvement
---

# FredAI Improvement — {now.strftime('%Y-%m-%d %H:%M UTC')}

## What Changed
{what}

## Details
{details}
"""
    fpath.write_text(text)


def write_signal_digest(signals: list[dict], period_hours: int = 4):
    """Write top signals to vault for persistence beyond SQLite."""
    if not vault_available() or not signals:
        return
    ensure_dirs()
    now = datetime.utcnow()
    fname = now.strftime("%Y-%m-%d-%H%M") + "-signals.md"
    fpath = SIGNAL_DIR / fname
    bull = sum(1 for s in signals if s.get("signal_type") == "bullish")
    bear = sum(1 for s in signals if s.get("signal_type") == "bearish")
    lines = [f"---\ndate: {now.isoformat()}\nperiod_hours: {period_hours}\ntotal_signals: {len(signals)}\ntags:\n  - fredai\n  - signals\n---\n",
             f"# Signal Digest — {now.strftime('%Y-%m-%d %H:%M UTC')}\n",
             f"**{len(signals)} signals** | Bullish: {bull} | Bearish: {bear}\n\n## Top Signals\n"]
    for s in signals[:30]:
        asset = f"[{s['asset']}] " if s.get("asset") else ""
        lines.append(f"- **{asset}{s.get('author','')}**: {s.get('content','')[:120]} _(sentiment: {s.get('signal_type','')}, {s.get('sentiment_score',0):.2f})_\n")
    fpath.write_text("".join(lines))


def _update_active_context(status_line: str):
    """Update the ActiveContext.md with current FredAI status."""
    if not ACTIVE_CTX.exists():
        return
    try:
        content = ACTIVE_CTX.read_text()
        now = datetime.utcnow()
        # Update the 'Current focus' line if present
        import re
        new_focus = f"FredAI active — {status_line} ({now.strftime('%Y-%m-%d %H:%M UTC')})"
        content = re.sub(r"(## Current focus\n).*?(\n\n)", rf"\1{new_focus}\2", content, flags=re.DOTALL)
        content = re.sub(r"updated: .*", f"updated: {now.isoformat()[:16]}", content)
        ACTIVE_CTX.write_text(content)
    except Exception:
        pass
