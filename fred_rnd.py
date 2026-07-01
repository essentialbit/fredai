"""
FredAI R&D Discovery Engine
============================
North star: Build the world's first Financial Super Intelligence (FSI).
Every proposal generated here must advance Fred along the 6-level FSI roadmap.

FSI Levels:
  L1 Signal Intelligence      — done
  L2 Pattern Intelligence     — active
  L3 Predictive Intelligence  — next
  L4 Reasoning Intelligence
  L5 World Model
  L6 Super Intelligence

Runs every 6 hours alongside the improvement cycle.
"""

import json
import re
from datetime import datetime
from pathlib import Path
import anthropic
import os

from memory_store import get_signals, get_trending_assets, get_summaries
from claude_code_agent import ClaudeCodeAgent

PROJECT_ROOT = Path(__file__).parent


# ── FSI CAPABILITY MAP ────────────────────────────────────────────────────────
# Every candidate maps to an FSI level. R&D picks the highest-impact feasible
# item that advances the current level or unlocks the next one.

RND_AREAS = {

    # ── L1: Signal Intelligence (complete — maintain only) ──────────────────
    "l1_signal_maintenance": {
        "fsi_level": 1,
        "description": "Maintain and harden existing L1 signal pipeline",
        "candidates": [
            "Improve X/Twitter deduplication using semantic similarity",
            "Add cashtag extraction for ASX tickers ($BHP.AX format)",
            "Signal freshness decay — weight recent signals higher",
            "Source reliability scoring (track which sources precede price moves)",
        ]
    },

    # ── L2: Pattern Intelligence (active development) ───────────────────────
    "l2_sentiment_upgrade": {
        "fsi_level": 2,
        "description": "Replace VADER with domain-specific financial NLP",
        "candidates": [
            "FinBERT sentiment (ProsusAI/finbert via HuggingFace transformers — free, state-of-art)",
            "FinBERT-tone: detects forward guidance tone in earnings calls",
            "Named entity recognition linking tweet companies to tickers (spaCy)",
            "Aspect-based sentiment: extract per-company sentiment from multi-company tweets",
            "Sarcasm detection for financial text (fine-tuned RoBERTa)",
        ]
    },
    "l2_new_signal_sources": {
        "fsi_level": 2,
        "description": "Expand signal inputs beyond X/Twitter",
        "candidates": [
            "Reddit sentiment: r/wallstreetbets + r/investing (PRAW, free)",
            "Fear & Greed Index (CNN Business API — free, no key)",
            "SEC insider trading Form 4 feed (EDGAR full-text search API — free)",
            "Short interest data (Finviz scrape — free)",
            "Bitcoin on-chain metrics (Glassnode free tier: SOPR, MVRV, exchange flows)",
            "Unusual options activity (Unusual Whales free webhook)",
            "StockTwits API (cashtag-native, financial-only feed — free tier)",
            "YouTube transcript sentiment (Bloomberg/CNBC via yt-dlp + Whisper)",
            "Earnings call transcript sentiment (Seeking Alpha earnings transcripts)",
        ]
    },
    "l2_pattern_detection": {
        "fsi_level": 2,
        "description": "Find structure across signals, assets, and time",
        "candidates": [
            "Rolling cross-asset correlation matrix (returns last 30/90/180 days)",
            "Sector rotation detection (money moving between sectors)",
            "Signal clustering by theme (inflation, AI, energy, crypto — BERTopic)",
            "Influence-weighted sentiment (weight by follower count / engagement)",
            "Divergence detector: price up but sentiment down (or vice versa)",
            "Volume-sentiment correlation: high volume + bearish = capitulation signal",
            "Earnings calendar integration with pre/post signal analysis",
            "52-week high/low proximity alert (overbought/oversold context)",
        ]
    },
    "l2_market_structure": {
        "fsi_level": 2,
        "description": "Market microstructure signals",
        "candidates": [
            "Options flow: put/call ratio per asset (Yahoo Finance options chain)",
            "Options implied volatility (IV) surface — term structure steepening",
            "Short interest change rate (Finviz: short % of float, days-to-cover)",
            "Dark pool print detection (Unusual Whales free feed)",
            "Market breadth: advance/decline ratio (Yahoo Finance summary stats)",
            "VIX term structure (spot vs futures — contango signals calm, backwardation = fear)",
            "Commodity futures curve shape (contango/backwardation for oil, gold, copper)",
        ]
    },

    # ── L3: Predictive Intelligence ─────────────────────────────────────────
    "l3_backtesting": {
        "fsi_level": 3,
        "description": "Ground-truth loop: measure whether Fred's signals predict price",
        "candidates": [
            "Signal outcome tracker: log prediction at T, measure price at T+4h/24h/72h",
            "Per-source accuracy scoring: which signal sources actually precede price moves?",
            "Sentiment reversal → price reversal lag study (how many hours?)",
            "VADER vs FinBERT accuracy comparison on held-out signal set",
            "Backtesting framework for technical alerts (RSI oversold → bounce %)",
            "Information coefficient (IC) per signal type (Spearman rank correlation)",
        ]
    },
    "l3_anomaly_detection": {
        "fsi_level": 3,
        "description": "Detect when something unusual is happening before price reacts",
        "candidates": [
            "Signal volume spike detector (Z-score > 3 = anomaly alert)",
            "Sentiment velocity: rate of change in sentiment (flash crash precursor)",
            "Cross-asset contagion: correlation breakdown detection (LASSO or DCC-GARCH)",
            "Earnings surprise prediction: pre-earnings sentiment → EPS beat/miss",
            "Unusual options activity → price move prediction (UOA backtested)",
            "Dark pool print clustering → directional signal",
            "Short squeeze risk scoring (high short % + rising price + low float)",
        ]
    },
    "l3_macro_intelligence": {
        "fsi_level": 3,
        "description": "Understand the macro regime Fred is operating in",
        "candidates": [
            "FRED API macro indicators: CPI, PCE, PMI, unemployment, yield curve (free, no key)",
            "Yield curve shape classifier (normal/flat/inverted → regime label)",
            "Inflation regime detector (high/low/transitioning)",
            "Rate cycle position (hiking/cutting/paused → sector rotation implications)",
            "Economic surprise index (actual vs consensus macro data)",
            "Recession probability model (Sahm Rule, yield curve, leading indicators)",
            "Seasonal pattern recognition: Santa rally, September effect, earnings season",
        ]
    },
    "l3_portfolio_risk": {
        "fsi_level": 3,
        "description": "Quantitative portfolio risk and position sizing",
        "candidates": [
            "Portfolio Value-at-Risk (VaR) at 95%/99% confidence",
            "Sharpe ratio per position (rolling 90d)",
            "Maximum drawdown tracking per position and portfolio",
            "Kelly Criterion position sizing calculator",
            "Sector concentration risk alert (>40% in one sector)",
            "Correlation-adjusted portfolio heat map",
            "10-year DCF valuation model (FRED risk-free rate + analyst growth estimates)",
        ]
    },

    # ── L4: Reasoning Intelligence ──────────────────────────────────────────
    "l4_multi_agent_reasoning": {
        "fsi_level": 4,
        "description": "Multiple specialised AI agents debating and synthesising market views",
        "candidates": [
            "Bull Agent vs Bear Agent debate: generate opposing theses per asset, Arbiter synthesises",
            "Devil's Advocate mode: Fred challenges its own bullish thesis with the strongest bear case",
            "Consensus tracker: when Fred's view aligns with market consensus, flag overconfidence risk",
            "Multi-timeframe agent: short-term (1w), medium-term (3m), long-term (3y) agents per asset",
        ]
    },
    "l4_fundamental_intelligence": {
        "fsi_level": 4,
        "description": "Deep analysis of company fundamentals and institutional positioning",
        "candidates": [
            "SEC EDGAR 10-K/10-Q parser: revenue growth, margin trends, debt, FCF (EDGAR free API)",
            "13F institutional positioning: what are Berkshire, Bridgewater, Renaissance holding?",
            "Insider buying clusters: when multiple insiders buy same week → strong signal",
            "CEO letter sentiment analysis: annual report language → management confidence score",
            "Patent filing velocity as R&D proxy (USPTO API — free)",
            "Job listing trends as hiring/growth signal (LinkedIn/Indeed scrape or Thinknum)",
        ]
    },
    "l4_causal_reasoning": {
        "fsi_level": 4,
        "description": "Why markets move — causal attribution, not just correlation",
        "candidates": [
            "Event attribution: when price moves > 2%, Fred identifies the likely cause from signals",
            "Hypothesis testing: Fred states thesis → tests statistically → updates confidence",
            "Counterfactual analysis: 'BTC would be X if Fed hadn't hiked' — scenario modelling",
            "Central bank language delta: Fed/RBA/ECB statement semantic change score (spaCy)",
            "Causal chain mapping: macro event → sector → stock (DAG representation)",
            "Geopolitical risk scoring: cluster news by conflict zone, sanction events",
        ]
    },

    # ── L5: World Model ─────────────────────────────────────────────────────
    "l5_alternative_data": {
        "fsi_level": 5,
        "description": "Data sources beyond traditional financial feeds",
        "candidates": [
            "Satellite imagery: shipping vessel tracking (MarineTraffic free tier)",
            "Container shipping rates (Freightos Baltic Index — free public data)",
            "GitHub commit velocity as tech company health proxy (GitHub public API)",
            "App download rankings as consumer sentiment (App Annie / SensorTower free)",
            "Google Trends financial keywords (pytrends — free, no key)",
            "Wikipedia article view spikes as attention signal (Wikimedia API — free)",
            "Supply chain stress: Baltic Dry Index, Harpex shipping index",
        ]
    },
    "l5_agent_swarms": {
        "fsi_level": 5,
        "description": "Specialised agent network covering every market sector",
        "candidates": [
            "Tech sector agent: chips, software, cloud, AI (Mag7 + semiconductors specialist)",
            "Energy agent: oil/gas, renewables, uranium — tracks production, policy, geopolitics",
            "Financials agent: banks, insurance, credit — tracks rate sensitivity, loan books",
            "Crypto agent: on-chain, DeFi, regulatory, BTC dominance, L2 growth",
            "Macro agent: central banks, yield curves, FX, commodities",
            "Swarm synthesis: when 4/5 agents align → high-conviction cross-sector signal",
        ]
    },
    "l5_model_training": {
        "fsi_level": 5,
        "description": "Fine-tune or adapt open LLMs for financial reasoning",
        "candidates": [
            "Fine-tune Llama 3.1 8B on Fred's signal history + price outcomes (QLoRA, 24GB GPU)",
            "FinGPT: open-source financial LLM (HuggingFace — already pretrained on financial corpora)",
            "Retrieval-augmented generation (RAG) over Fred's historical signal store",
            "Prompt-optimisation loop: measure which Fred briefing formats correlate with user action",
            "Embedding store for semantic signal search (sentence-transformers + FAISS — free)",
        ]
    },

    # ── L6: Super Intelligence ───────────────────────────────────────────────
    "l6_autonomous_research": {
        "fsi_level": 6,
        "description": "Fred directs its own research agenda without human prompting",
        "candidates": [
            "Self-directed signal discovery: Fred proposes new data sources, tests them, adopts or rejects",
            "Autonomous hypothesis market: Fred tracks its own prediction accuracy over time",
            "Edge detection: signals that precede consensus by 24-72h — identified autonomously",
            "Self-rewriting briefing templates based on which formats preceded correct calls",
            "Cross-instance learning: anonymised edge sharing between deployed Fred instances",
            "Autonomous portfolio recommendation with full backtested track record and risk disclosure",
        ]
    },
}


# ── FSI-ALIGNED DISCOVERY PROMPT ─────────────────────────────────────────────

DISCOVERY_PROMPT = """You are FredAI's R&D discovery agent. Your sole mission: identify the highest-value next capability that advances Fred toward Financial Super Intelligence (FSI).

## FSI North Star
Build the world's first Financial Super Intelligence — an AI that outthinks every Bloomberg terminal, every quant desk, and every analyst on Earth. Fred runs on everyday hardware. Fred is free. Fred improves every 6 hours.

## FSI Roadmap (evaluate every proposal against this)
- L1 Signal Intelligence ✅ — done (X/Twitter, VADER, yfinance, 4h briefings)
- L2 Pattern Intelligence 🔄 — FinBERT, cross-asset correlation, options flow, insider trades, Fear&Greed
- L3 Predictive Intelligence 🔲 — backtesting, anomaly detection, macro regime, earnings prediction
- L4 Reasoning Intelligence 🔲 — multi-agent debate, causal attribution, 10-K analysis, 13F positioning
- L5 World Model 🔲 — alternative data, agent swarms, fine-tuned LLM
- L6 Super Intelligence 🔲 — self-directing, novel edge discovery, autonomous recommendations

## Current Fred capabilities
{current_capabilities}

## Full FSI capability map (by level)
{areas}

## Live signal stats
{signal_stats}

## Your job
Select the top 5 proposals that will most advance Fred toward FSI. Prioritise:
1. The highest feasible FSI level (push toward L2 completion before starting L3)
2. Compounding improvements (build on what exists, not isolated features)
3. Free / open-source tools (HuggingFace, EDGAR, FRED API, CoinGecko, etc.)
4. Measurable improvements (can we backtest this? if not, deprioritise)
5. Raspberry Pi 4 compatible (no GPU requirements unless there's a CPU fallback)

Return a JSON array of exactly 5 proposals:
[
  {{
    "title": "Short descriptive title",
    "category": "l2_sentiment_upgrade|l2_new_signal_sources|l2_pattern_detection|l2_market_structure|l3_backtesting|l3_anomaly_detection|l3_macro_intelligence|l3_portfolio_risk|l4_multi_agent_reasoning|l4_fundamental_intelligence|l4_causal_reasoning|l5_alternative_data|l5_agent_swarms|l5_model_training|l6_autonomous_research",
    "fsi_level": 2,
    "description": "What it does, why it advances FSI, what financial edge it creates",
    "compounds_with": ["VADER sentiment pipeline", "yfinance market data"],
    "free_tools": ["HuggingFace ProsusAI/finbert", "transformers library"],
    "implementation_spec": "Specific Python changes: which file to modify, which function to add, which library to pip install. Be precise — this will be passed directly to a code agent.",
    "estimated_hours": 4,
    "impact_score": 9.2,
    "priority": 1
  }}
]

Respond with raw JSON array only — no code fences, no explanation outside the JSON."""


def _get_current_capabilities() -> str:
    files = [f.name for f in PROJECT_ROOT.glob("*.py") if not f.name.startswith("_")]
    return f"""
L1 complete:
- X/Twitter signal scraping (requests + X API v2)
- VADER financial sentiment scoring
- yfinance market data (26 assets: US equities, ASX blue chips, crypto, ETFs)
- 4-hour Claude-powered briefings (long-term investing lens, contrarian focus)
- Multi-user auth with watchlist + portfolio P&L tracking
- Trend detection (sentiment shift, volume spikes, price alerts)
- APScheduler 6h improvement cycle + community engagement
- Flask + SocketIO dashboard (dark finance theme)
- SQLite memory store (signals, trends, summaries, alerts, backlog)
- GitHub R&D self-improvement loop (ClaudeCodeAgent)
- Autonomous device installer (macOS/Linux/Windows/Pi)
- CI/CD pipeline (multi-arch Docker, auto-release)
- 3D Signal Globe (globe.gl WebGL)
- YouTube video intelligence (Bloomberg/CNBC/Yahoo Finance RSS)

Active modules: {', '.join(sorted(files))}
"""


def run_discovery(client: anthropic.Anthropic = None) -> list[dict]:
    """Run a FSI-aligned discovery cycle and return prioritised proposals."""
    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    signals = get_signals(hours=24)
    trending = get_trending_assets(hours=4, limit=10)
    signal_stats = (
        f"{len(signals)} signals in 24h | "
        f"Top assets: {[t['asset'] for t in trending[:5]]} | "
        f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )

    prompt = DISCOVERY_PROMPT.format(
        current_capabilities=_get_current_capabilities(),
        areas=json.dumps(RND_AREAS, indent=2),
        signal_stats=signal_stats,
    )

    print("[RnD] Running FSI discovery cycle...")
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            proposals = json.loads(match.group())
            for p in proposals:
                lvl = p.get("fsi_level", "?")
                print(f"  L{lvl}: {p.get('title','?')} (impact={p.get('impact_score','?')})")
            return proposals
    except Exception as e:
        print(f"[RnD] Discovery error: {e}")
    return []


def run_rnd_cycle(implement: bool = True) -> dict:
    """
    Full FSI-driven R&D cycle:
    1. Discover highest-value FSI capability improvements
    2. Queue into backlog with fsi_level metadata
    3. Implement top proposal via ClaudeCodeAgent
    4. Update MISSION.md level checklist if L2 item completed
    """
    from memory_store import (
        insert_feature_proposal, get_top_proposals,
        mark_proposal_in_progress, mark_proposal_done
    )
    from obsidian_bridge import write_improvement_log

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    results = {"discovered": 0, "implemented": None, "error": None}

    # Step 1: Discover
    proposals = run_discovery(client)
    if proposals:
        from github_sync import sync_proposal_to_issue
        for p in proposals:
            description = (
                f"[FSI L{p.get('fsi_level','?')}] {p.get('description','')}\n\n"
                f"Compounds with: {', '.join(p.get('compounds_with', []))}\n"
                f"Free tools: {', '.join(p.get('free_tools', []))}"
            )
            category = p.get("category", "general")
            estimated_hours = p.get("estimated_hours", 2)
            impact_score = p.get("impact_score", 5.0)
            proposal_id = insert_feature_proposal(
                title=p.get("title", "Untitled"),
                description=description,
                category=category,
                implementation_spec=p.get("implementation_spec", ""),
                estimated_hours=estimated_hours,
                impact_score=impact_score,
                priority=p.get("priority", 3),
                proposed_by="claude",
            )
            try:
                sync_proposal_to_issue({
                    "id": proposal_id, "title": p.get("title", "Untitled"),
                    "description": description, "category": category,
                    "implementation_spec": p.get("implementation_spec", ""),
                    "estimated_hours": estimated_hours, "impact_score": impact_score,
                    "proposed_by": "claude",
                })
            except Exception as e:
                print(f"[RnD] Issue sync failed for '{p.get('title')}': {e}")
        results["discovered"] = len(proposals)
        results["fsi_levels"] = [p.get("fsi_level") for p in proposals]

    # Step 2: Pick and implement top proposal
    if implement:
        top = get_top_proposals(status="proposed", limit=1)
        if top:
            proposal = top[0]
            print(f"\n[RnD] Implementing: {proposal['title']}")
            mark_proposal_in_progress(proposal["id"])

            from improve import create_agent_branch
            branch = create_agent_branch(proposal["id"], "claude")
            results["branch"] = branch

            agent = ClaudeCodeAgent(model="claude-opus-4-8", max_iterations=20)
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
                what=f"FSI R&D: {proposal['title']}",
                details=(
                    f"FSI Roadmap: advancing toward L{proposal.get('category','?')[1] if proposal.get('category','?')[1:2].isdigit() else '?'}\n"
                    f"Success: {impl_result['success']}\n"
                    f"Files: {impl_result['files_changed']}\n"
                    f"{impl_result['summary']}"
                )
            )

    return results
