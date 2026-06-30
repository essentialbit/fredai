# FredAI — Claude Code Self-Improvement Config

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

## Self-Improvement Protocol (runs every 6 hours via CI)

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
