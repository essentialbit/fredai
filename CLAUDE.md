# FredAI — Claude Code Self-Improvement Config

## 🔒 Sensor Protected — Do Not Disrupt
The hourly `com.essentialbit.fredai.sensor` launchd job, its watchdog script, state dir (`~/.claude/fred-sensor/`), and any `claude -p` process it spawns must never be unloaded, deleted, edited, or killed by any session (interactive or headless) working in this repo — unless the user explicitly instructs termination live, in that session. This overrides any autonomous/pre-authorised operating mode. Status checks (`launchctl list`, heartbeat/log reads) are always fine.

## Project
FredAI is an AI-powered financial intelligence dashboard with:
- X/Twitter signal scraping + VADER sentiment analysis
- Multi-user auth with per-user watchlists, portfolios, and learned interests
- Live market data (yfinance) + TradingView-style charts
- Claude-powered 4-hour briefings and conversational advisor ("Fred")
- SQLite memory store at `data/sentinel.db`
- Flask + SocketIO backend on port 8080
- Obsidian vault integration at `/Volumes/Iron 1TBSSD/Shared/Obsidian Vault/`

## Tech Stack
- Python 3.14 | Flask + Flask-SocketIO + eventlet
- APScheduler (4h scan cycle, 1min market refresh)
- VADER sentiment + Anthropic claude-sonnet-4-6
- yfinance for market data
- SQLite (no tweepy — use requests for X API v2)
- Lightweight Charts (TradingView) + Chart.js
- Inter + JetBrains Mono fonts
- Dark finance theme (#03080f, #00ff88, #ff3b5c, #00b4ff)

## Key Files
- `main.py` — Flask app, routes, WebSocket, scheduler
- `agent.py` — FredAI persona, Claude integration (PRESERVE soul.md personality)
- `soul.md` — Fred's identity and operating contract (DO NOT alter Fred's core values)
- `memory_store.py` — SQLite: users, watchlist, portfolio, signals, trends, summaries
- `twitter_client.py` — X API v2 via requests (no tweepy)
- `market_data.py` — yfinance price/history fetching
- `trend_detector.py` — sentiment shift detection, alerts
- `templates/dashboard.html` — Single-file frontend (login + 4 tabs + Fred chat)
- `config.py` — API keys from .env
- `data/sentinel.db` — SQLite database

## Self-Improvement Protocol — North Star: Financial Super Intelligence (FSI)

**Overarching goal:** Every 6-hour cycle must measurably advance Fred toward becoming the world's first Financial Super Intelligence. This is not a maintenance loop — it is a capability-building engine. Every implementation decision must be evaluated against the FSI roadmap in `MISSION.md`.

**The 6 FSI levels (read MISSION.md for full detail):**
- L1 Signal Intelligence ✅ — multi-source sentiment, live price data, 4h briefings (complete)
- L2 Pattern Intelligence 🔄 — FinBERT, cross-asset correlation, options flow, insider filings, Fear&Greed
- L3 Predictive Intelligence 🔲 — backtesting, anomaly detection, macro regime, earnings prediction
- L4 Reasoning Intelligence 🔲 — multi-agent debate, causal attribution, 10-K analysis, 13F positioning
- L5 World Model 🔲 — cross-market contagion, alternative data, fine-tuned LLM, agent swarms
- L6 Super Intelligence 🔲 — self-directing research, novel edge discovery, autonomous recommendations

**Evaluation criterion for every proposed improvement:** "Does this push Fred closer to L6? If not, is it critical infrastructure that unblocks L2+ work?" If neither is true, deprioritise it.

When invoked for improvement cycles:

### Step 1 — Research
Search for latest trends in:
- Financial dashboard design (Bloomberg, Refinitiv, FactSet patterns)
- New financial data sources (free or low-cost APIs)
- New NLP/signal extraction techniques for financial text
- Market microstructure signals (options flow, dark pool, etc.)
- Portfolio risk metrics (VaR, Sharpe, max drawdown)

### Step 2 — Identify Gaps
Review `data/sentinel.db` for:
- Assets with high price moves but zero X signal coverage
- Signals that consistently mispredicted price direction
- Users with empty portfolios (opportunity to prompt onboarding)
- Trend alerts that fired but led to no observable price change

### Step 3 — Implement
Priority order for improvements:
1. **Signal quality** — better filtering, deduplication, influence weighting
2. **Dashboard visualizations** — new chart types, better UX
3. **Fred's intelligence** — better prompts, new data sources
4. **Coverage gaps** — add missing asset classes, new search queries
5. **Performance** — caching, query optimization

### Step 4 — Test
```bash
source venv/bin/activate
python3 -c "from main import *; print('Import OK')"
python3 -m pytest tests/ -q 2>/dev/null || echo "No tests yet"
```

### Step 5 — Commit
```bash
git add -A
git commit -m "auto-improve: <what changed>"
git push origin main
```

### Step 6 — Obsidian Journal
Write improvement log to vault:
```
/Volumes/Iron 1TBSSD/Shared/Obsidian Vault/AI/SMC/FredAI/improvements/YYYY-MM-DD-HH.md
```

## Deployment Targets (from Raspberry Pi to hyperscaler — Fred runs everywhere)

Fred must remain deployable across the entire compute spectrum:

| Target | Constraints | Adaptation |
|--------|------------|------------|
| Apple Watch / wearable | Companion-only (no server) | Lightweight JSON API client, SwiftUI |
| Raspberry Pi Zero | 512MB RAM, ARM32 | Minimal mode: no heavy ML, SQLite only |
| Raspberry Pi 4 | 4-8GB RAM, ARM64 | Full stack (yfinance + Claude) |
| MacBook / PC | Full stack | Default mode |
| Cloud VM (1-2 vCPU) | Docker, 2GB RAM | docker-compose, minimal deps |
| Hyperscaler (Kubernetes) | Horizontal scale | Stateless API layer + external DB |

### Adaptive startup mode (auto-detects environment)

```python
# main.py detects RAM and scales accordingly
import psutil
RAM_GB = psutil.virtual_memory().total / 1e9
LITE_MODE = RAM_GB < 1.0  # Raspberry Pi Zero / wearable companion
```

In LITE_MODE:
- Skip yfinance heavy batch fetch (use single-ticker on demand)
- Skip APScheduler R&D cycle
- Compress SQLite journal more aggressively
- Serve minimal dashboard (no Chart.js, text-based KPIs)

### Docker Compose is the primary deployment mechanism
- Works: macOS, Windows, Linux, Raspberry Pi (ARM64), any cloud VM
- Image: ghcr.io/essentialbit/fredai:latest (auto-published on push)
- No OS dependencies beyond Docker

### Environment variable configuration (all platforms)
Every configurable value is an env var — no hardcoded platform checks.
This means the same image runs everywhere; the host supplies the profile.

## Code Standards
- No comments unless the WHY is non-obvious
- No trailing summaries in responses
- Preserve the dark finance theme colors (see CSS variables)
- All API calls go through config.py — never hardcode keys
- SQLite only — no external databases
- WebSocket events: `market_update`, `new_signal`, `summary_update`, `alert`, `timeline_update`, `chat_response`
- All user data is per user_id — never mix users

## Obsidian Vault Paths (for logging and context)
- Signals log: `AI/SMC/FredAI/signals/`
- Improvements: `AI/SMC/FredAI/improvements/`
- Summaries mirror: `AI/SMC/FredAI/summaries/`
- Active context: `AI/Shared/ActiveContext.md`
