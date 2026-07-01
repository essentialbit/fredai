"""
FredAI Gemini R&D Discovery Engine
===================================
Uses Google Gemini API to discover FSI-aligned proposals and implement them
autonomously via GeminiCodeAgent.
"""

import json
import re
import os
from datetime import datetime, UTC
from pathlib import Path
import requests

from memory_store import get_signals, get_trending_assets, get_summaries
from gemini_code_agent import GeminiCodeAgent
from fred_rnd import RND_AREAS, DISCOVERY_PROMPT, _get_current_capabilities

PROJECT_ROOT = Path("/Volumes/Iron 1TBSSD/Claude/FredAI")

def run_gemini_discovery() -> list[dict]:
    """Run a Gemini-driven FSI discovery cycle."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[Gemini RnD] GEMINI_API_KEY not configured")
        return []

    signals = get_signals(hours=24)
    trending = get_trending_assets(hours=4, limit=10)
    signal_stats = (
        f"{len(signals)} signals in 24h | "
        f"Top assets: {[t['asset'] for t in trending[:5]]} | "
        f"Timestamp: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    prompt = DISCOVERY_PROMPT.format(
        current_capabilities=_get_current_capabilities(),
        areas=json.dumps(RND_AREAS, indent=2),
        signal_stats=signal_stats,
    )

    print("[Gemini RnD] Running FSI discovery cycle...")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    # We can use the response schema to enforce the structure!
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "category": {"type": "string"},
                "fsi_level": {"type": "integer"},
                "description": {"type": "string"},
                "compounds_with": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "free_tools": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "implementation_spec": {"type": "string"},
                "estimated_hours": {"type": "number"},
                "impact_score": {"type": "number"},
                "priority": {"type": "integer"}
            },
            "required": ["title", "category", "fsi_level", "description", "compounds_with", "free_tools", "implementation_spec", "estimated_hours", "impact_score", "priority"]
        }
    }

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    try:
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(text)
        print(f"  [Gemini RnD API] Status {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Gemini RnD] Discovery error: {e}")
    return []

def run_gemini_rnd_cycle(implement: bool = True) -> dict:
    """Run full Gemini R&D cycle."""
    from memory_store import (
        insert_feature_proposal, get_top_proposals,
        mark_proposal_in_progress, mark_proposal_done
    )
    from obsidian_bridge import write_improvement_log

    results = {"discovered": 0, "implemented": None, "error": None}

    # Step 1: Discover
    proposals = run_gemini_discovery()
    if proposals:
        for p in proposals:
            insert_feature_proposal(
                title=f"[Gemini] {p.get('title', 'Untitled')}",
                description=(
                    f"[FSI L{p.get('fsi_level','?')}] {p.get('description','')}\n\n"
                    f"Compounds with: {', '.join(p.get('compounds_with', []))}\n"
                    f"Free tools: {', '.join(p.get('free_tools', []))}"
                ),
                category=p.get("category", "general"),
                implementation_spec=p.get("implementation_spec", ""),
                estimated_hours=p.get("estimated_hours", 2),
                impact_score=p.get("impact_score", 5.0),
                priority=p.get("priority", 3),
            )
        results["discovered"] = len(proposals)
        results["fsi_levels"] = [p.get("fsi_level") for p in proposals]

    # Step 2: Pick and implement top proposal
    if implement:
        # We fetch proposals created by Gemini
        # Since titles are prefixed with '[Gemini] ', we can search specifically or pick the top proposed
        top = get_top_proposals(status="proposed", limit=10)
        gemini_proposals = [p for p in top if p["title"].startswith("[Gemini]")]
        
        if gemini_proposals:
            proposal = gemini_proposals[0]
            print(f"\n[Gemini RnD] Implementing: {proposal['title']}")
            mark_proposal_in_progress(proposal["id"])

            agent = GeminiCodeAgent(model="gemini-2.5-flash", max_iterations=20)
            task = (
                f"FSI MISSION: Build the world's first Financial Super Intelligence.\n\n"
                f"TASK: {proposal['title']}\n\n"
                f"{proposal['description']}\n\n"
                f"IMPLEMENTATION SPEC:\n{proposal.get('implementation_spec', '')}\n\n"
                f"CONSTRAINTS:\n"
                f"- Must work on Raspberry Pi 4 (no GPU-only dependencies)\n"
                f"- Use free/open-source tools only\n"
                f"- Build on existing pipeline (don't replace, extend)\n"
                f"- All changes must pass: python3 -c 'from main import app; print(\"OK\")'"
            )
            impl_result = agent.implement(task)

            mark_proposal_done(proposal["id"], success=impl_result["success"], notes=impl_result["summary"])
            results["implemented"] = {
                "proposal": proposal["title"],
                "success": impl_result["success"],
                "files_changed": impl_result["files_changed"],
                "summary": impl_result["summary"][:200],
            }

            write_improvement_log(
                what=f"FSI Gemini R&D: {proposal['title']}",
                details=(
                    f"FSI Roadmap: advancing toward L{proposal.get('category','?')[1] if proposal.get('category','?')[1:2].isdigit() else '?'}\n"
                    f"Success: {impl_result['success']}\n"
                    f"Files: {impl_result['files_changed']}\n"
                    f"{impl_result['summary']}"
                )
            )

    return results
