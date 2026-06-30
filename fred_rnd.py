"""
FredAI R&D Discovery Engine
============================
Continuously researches the frontier of financial AI, identifies capability
gaps, generates implementation specs, and queues them into the feature backlog.

Runs every 6 hours alongside the improvement cycle.
"""

import json
from datetime import datetime
from pathlib import Path
import anthropic
import os

from memory_store import get_signals, get_trending_assets, get_summaries
from claude_code_agent import ClaudeCodeAgent

PROJECT_ROOT = Path(__file__).parent


# ── R&D KNOWLEDGE BASE ────────────────────────────────────────────────────────
# Categories of capability Fred could acquire — updated by each cycle

RND_AREAS = {
    "signal_sources": {
        "description": "New financial signal inputs beyond X/Twitter",
        "candidates": [
            "Options flow (unusual call/put activity via free APIs)",
            "Reddit r/wallstreetbets / r/investing sentiment",
            "Google Trends financial keyword correlation",
            "Earnings call transcript sentiment (SEC EDGAR)",
            "Insider trading filings (SEC Form 4)",
            "Short interest data (Finviz scrape)",
            "Fear & Greed Index (CNN Business API)",
            "Credit default swap spreads",
            "Commodity futures curve shape (contango/backwardation)",
            "Bitcoin on-chain metrics (Glassnode free tier)",
        ]
    },
    "ai_intelligence": {
        "description": "Smarter analysis techniques for Fred",
        "candidates": [
            "FinBERT sentiment (better than VADER for finance text)",
            "Named entity recognition to link companies in tweets",
            "Earnings surprise prediction from signal patterns",
            "Multi-signal consensus scoring (when 3+ sources agree)",
            "Anomaly detection on signal volume spikes",
            "Backtesting framework for signal accuracy",
            "Contrarian signal scoring (high bearish + low price = buy)",
            "Semantic clustering of signals by theme",
        ]
    },
    "portfolio_intelligence": {
        "description": "Smarter portfolio management tools",
        "candidates": [
            "Sharpe ratio calculator per position",
            "Max drawdown tracking",
            "Correlation matrix between holdings",
            "Kelly criterion position sizing",
            "10-year DCF valuation calculator",
            "Sector concentration alerts",
            "Rebalancing suggestions when thesis reached",
            "Dividend yield tracking",
        ]
    },
    "dashboard_visualizations": {
        "description": "New chart types and visual intelligence",
        "candidates": [
            "RSI + MACD technical overlay on price chart",
            "Volume profile chart",
            "Options chain visualization",
            "Correlation heatmap between portfolio assets",
            "Signal accuracy scorecard (historical)",
            "Earnings calendar with signal pre/post analysis",
            "Market breadth indicators (advance/decline)",
            "52-week high/low indicator",
        ]
    },
    "data_sources": {
        "description": "New free/low-cost financial data APIs",
        "candidates": [
            "Alpha Vantage (free fundamental data)",
            "FRED API (economic indicators — free)",
            "SEC EDGAR full-text search",
            "Polygon.io (free tier)",
            "Yahoo Finance (already via yfinance — expand usage)",
            "CoinGecko API (crypto — no key)",
            "Finviz scraping (market overview)",
            "Macrotrends.net historical data",
        ]
    },
    "agent_architecture": {
        "description": "Fred's own AI capabilities and self-improvement",
        "candidates": [
            "Memory-augmented retrieval (semantic search over signal history)",
            "User behavior learning (what signals the user acts on)",
            "Multi-agent: separate Bull and Bear agents debating each stock",
            "Automated hypothesis testing (signal predicted X, did X happen?)",
            "Natural language alert generation (Fred writes custom alerts)",
            "Portfolio Q&A with citations (Fred cites specific signals)",
            "Scheduled deep dives (every week, full analysis of top holdings)",
        ]
    }
}


DISCOVERY_PROMPT = """You are FredAI's R&D discovery agent. Your job is to identify the highest-value capability improvements for FredAI.

FredAI's purpose: Long-term high-growth investing advisor. Strategy: buy low sell high, 10-year horizon, 75-100% return targets, contrarian signals.

CURRENT FRED CAPABILITIES:
{current_capabilities}

CAPABILITY AREAS TO EVALUATE:
{areas}

RECENT SIGNAL STATS:
{signal_stats}

For each area, evaluate:
1. Impact on Fred's core mission (long-term high-growth advisory)
2. Feasibility to implement in Python/Flask/SQLite stack
3. Data availability (free or low-cost)
4. Time to implement (estimate)

Return a JSON array of the top 5 highest-value proposals:
[
  {{
    "title": "Short descriptive title",
    "category": "signal_sources|ai_intelligence|portfolio_intelligence|dashboard_visualizations|data_sources|agent_architecture",
    "description": "What it does and why it matters for Fred's mission",
    "implementation_spec": "Specific Python/JS implementation approach (file to modify, function to add, etc.)",
    "estimated_hours": 1,
    "impact_score": 8.5,
    "priority": 1
  }}
]

Focus on what will make Fred MOST useful for long-term high-growth investing decisions. Prioritize signal quality over cosmetics."""


def _get_current_capabilities() -> str:
    """Summarize what Fred currently does."""
    files = list(PROJECT_ROOT.glob("*.py"))
    names = [f.name for f in files if not f.name.startswith("_")]
    return f"""
- X/Twitter signal scraping (VADER sentiment, cashtag extraction)
- yfinance market data (prices, history, sector data)
- 4-hour Claude-powered briefings (long-term investing lens)
- Multi-user auth with watchlist + interest learning
- Portfolio P&L tracking
- Trend detection (sentiment shift, volume spikes)
- Nasdaq macro data (VIX, Treasuries, Gold via Data Link)
- SQLite memory (signals, trends, summaries, alerts)
- Obsidian vault bridge
- Self-improvement loop (claude_code_agent.py)
- Modules: {', '.join(names)}
"""


def run_discovery(client: anthropic.Anthropic = None) -> list[dict]:
    """Run a discovery cycle and return prioritized proposals."""
    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    signals = get_signals(hours=24)
    trending = get_trending_assets(hours=4, limit=10)
    signal_stats = f"{len(signals)} signals in 24h | Top assets: {[t['asset'] for t in trending[:5]]}"

    areas_text = json.dumps(RND_AREAS, indent=2)
    capabilities = _get_current_capabilities()

    prompt = DISCOVERY_PROMPT.format(
        current_capabilities=capabilities,
        areas=areas_text,
        signal_stats=signal_stats,
    )

    print("[RnD] Running discovery cycle...")
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text

        # Extract JSON from response
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            proposals = json.loads(match.group())
            print(f"[RnD] Discovered {len(proposals)} proposals")
            return proposals
    except Exception as e:
        print(f"[RnD] Discovery error: {e}")
    return []


def run_rnd_cycle(implement: bool = True) -> dict:
    """
    Full R&D cycle:
    1. Discover what to build
    2. Queue into backlog
    3. If implement=True, implement top proposal via ClaudeCodeAgent
    """
    from memory_store import insert_feature_proposal, get_top_proposals, mark_proposal_in_progress, mark_proposal_done
    from obsidian_bridge import write_improvement_log

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    results = {"discovered": 0, "implemented": None, "error": None}

    # Step 1: Discover
    proposals = run_discovery(client)
    if proposals:
        for p in proposals:
            insert_feature_proposal(
                title=p.get("title", "Untitled"),
                description=p.get("description", ""),
                category=p.get("category", "general"),
                implementation_spec=p.get("implementation_spec", ""),
                estimated_hours=p.get("estimated_hours", 2),
                impact_score=p.get("impact_score", 5.0),
                priority=p.get("priority", 3),
            )
        results["discovered"] = len(proposals)

    # Step 2: Pick top proposal to implement
    if implement:
        top = get_top_proposals(status="proposed", limit=1)
        if top:
            proposal = top[0]
            print(f"\n[RnD] Implementing: {proposal['title']}")
            mark_proposal_in_progress(proposal["id"])

            agent = ClaudeCodeAgent(model="claude-opus-4-8", max_iterations=20)
            task = f"{proposal['title']}\n\n{proposal['description']}\n\nIMPLEMENTATION SPEC:\n{proposal.get('implementation_spec','')}"
            impl_result = agent.implement(task)

            mark_proposal_done(proposal["id"], success=impl_result["success"], notes=impl_result["summary"])
            results["implemented"] = {
                "proposal": proposal["title"],
                "success": impl_result["success"],
                "files_changed": impl_result["files_changed"],
                "summary": impl_result["summary"][:200],
            }

            write_improvement_log(
                what=f"R&D implemented: {proposal['title']}",
                details=f"Success: {impl_result['success']}\nFiles: {impl_result['files_changed']}\n{impl_result['summary']}"
            )

    return results
