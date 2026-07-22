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
- `rag_store.py` / `rag_retriever.py` — Fred Recall: FTS5+embedding storage and retrieval over Fred's own accumulated intelligence (see FSI L4 note below)
- `calibration_engine.py` — Brier-scored self-calibration: per-source reliability weights fed into `confluence_engine.py`'s aggregation (see FSI L4 note below)
- `thesis_tracker.py` — living investment theses with evidence-fed assumption health monitoring, built on Fred Recall (see FSI L4 note below)
- `filing_intel.py` — 10-K/10-Q Risk Factors/MD&A paragraph diffing with materiality scoring, feeds signals + Fred Recall (see FSI L2/L4 note below). Distinct from `sec_8k_client.py` (8-K material-event monitoring, unrelated filing class)
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
- L4 Reasoning Intelligence 🔄 — multi-agent debate, causal attribution, **10-K/10-Q risk-language diffing — shipped**, 13F positioning, **Fred Recall (hybrid FTS5+vector RAG grounding chat/briefings in Fred's own signal/news/briefing/debate/filing/vault history, cited inline) — shipped**, **Calibration Engine (Brier-scored per-source reliability weighting, feeds confluence_engine + chat hedging) — shipped**, **Thesis Tracker (living, evidence-fed investment theses with LLM-decomposed falsifiable assumptions and auto-attached supporting/contradicting evidence) — shipped**
- L5 World Model 🔲 — cross-market contagion, alternative data, fine-tuned LLM, agent swarms
- L6 Super Intelligence 🔲 — self-directing research, novel edge discovery, autonomous recommendations

**Evaluation criterion for every proposed improvement:** "Does this push Fred closer to L6? If not, is it critical infrastructure that unblocks L2+ work?" If neither is true, deprioritise it.

**Fred Recall (FSI L4, shipped)**: `rag_store.py` (storage: `rag_chunks` + FTS5 `rag_fts`, source_types news/signal/briefing/debate/insider/entity_evidence/vault) + `rag_retriever.py` (BM25+cosine via Reciprocal Rank Fusion, recency decay, ticker boost). Write-time hooks are FTS-only (`embed=False`) at every ingestion path (news_client, reddit/twitter_client, ticker_debate, main.py's briefing/entity-evidence routes) — embedding happens asynchronously in the hourly `job_rag_embed_backlog` job, never inline on a hot path. `chat()` and `generate_summary()` in agent.py both call `retrieve()`/`format_context()` for grounded, cited context; `GET /api/recall?q=` + the dashboard's "Ask Fred's Memory" panel expose it directly. Per-user privacy enforced inside `rag_store.py` (global rows + caller's own `user_id` rows only), never left to the caller. `vault_semantic_search.py` is now a thin wrapper over `rag_store` (source_type='vault') — the old standalone `vault_embeddings` table is dead schema, left in place.

**Calibration Engine (FSI L4, shipped)**: `calibration_engine.py` turns each `signal_outcomes` row (from `backtesting_engine.py`) into a probabilistic forecast — `avg_sentiment` magnitude maps to a stated P(correct) in [0.5,1.0] when available, else a documented fixed 0.65 for deterministic binary-call sources (insider/short_interest/technical, which carry no magnitude in this codebase). Brier-scores each source at the 24h checkpoint over a 30-day window, maps to a `[0.2, 1.5]` reliability weight (pivot: brier=0.25 = neutral 1.0), pinning sources with `sample_n < 20` to neutral with a `low_sample` flag. Persisted to `calibration_scores` (one row per source) by the daily `job_calibration_refresh` job. Wired into `confluence_engine.py::compute_confluence()`'s score (not its `agreement`/`factor_count`, which stay raw/structural) behind `config.CALIBRATION_WEIGHTS_ENABLED` (default true; false reproduces the pre-calibration formula bit-for-bit — verified). `agent.py`'s existing track-record lines (chat + briefing) append `(reliability x1.3)`-style suffixes when a source's weight is meaningfully off-neutral. `GET /api/calibration` + the dashboard's "Fred's Calibration" panel (reliability diagram + per-source table) surface it, bad sources included, not hidden.

**Thesis Tracker (FSI L4, shipped)**: `thesis_tracker.py` — `theses`/`thesis_assumptions`/`thesis_evidence` tables (per-user, ownership enforced at the API layer in main.py, same `entity["user_id"] != session["user_id"]` pattern as `tracked_entities.py`). Creation flow: `decompose_thesis()` (chat-tier LLM) drafts 3-6 falsifiable assumptions from a natural-language statement as a preview only — the user edits before `create_thesis()` actually persists. Nightly `job_thesis_auto_evidence` runs `rag_retriever.retrieve()` per active thesis, classifies new chunks via the cheap summary tier (`classify_evidence()`), auto-attaches (capped 5/thesis/run, idempotent on `(thesis_id, rag_chunk_id)` — manual free-text evidence is never deduped this way since SQLite treats each NULL as distinct), and `check_assumption_health()` marks assumptions weakening/broken on ≥3/≥6 contradicting items in the trailing 7 days (recovers to intact once evidence ages out), alerting only on a genuine status *transition* — never spams on repeat calls. `suggested_conviction()` is a recency-weighted (14d half-life) evidence balance, purely advisory, never auto-applied to the user's stated conviction. `chat()` summarizes active theses into context via `format_context_summary()`. Full CRUD under `/api/theses/*` (login_required, owner-only) + a dashboard "Investment Theses" panel (composer, conviction dial, assumption health lights, evidence feed with manual attach). Owner-isolation and idempotency verified at the module level against a fresh temp DB (not a full Flask-test-client pass — the ownership check itself is a one-line pattern already proven by `tracked_entities.py`'s identical precedent, judged lower marginal value than the rest of the verification for this feature's scope).

**Filing Intelligence (FSI L2/L4, shipped)**: `filing_intel.py` — new `filings`/`filing_sections`/`filing_diffs` tables. Reuses `sec_client.py`'s CIK map/User-Agent/submissions-JSON pattern (same SEC fair-use posture, sequential requests, polite delay) to poll 10-K/10-Q filings; `_extract_section()` heuristically locates Item 1A Risk Factors / Item 7 MD&A by picking the start-pattern match with the LARGEST gap to the next Item heading (filters out table-of-contents false-positives, which sit right before the next heading with near-zero content). Extracted text capped at ~200KB (HARD CONSTRAINT); raw HTML above 8MB is skipped rather than parsed. `diff_paragraphs()` is a `difflib.SequenceMatcher` paragraph-level diff (added/removed/modified, with a change_ratio); `_prior_filings_for_diff()` picks the comparison filing(s) — **must filter to strictly-earlier `filed_date`, not just a different accession_number**, or a resumed/re-run cycle can pick a newer filing as "prior" and diff backwards (real bug caught in verification, fixed before shipping). `materiality_score()` combines section weight (Risk Factors > MD&A), change_ratio, a documented high-signal-vocabulary list (`going concern`/`material weakness`/`covenant`/`impairment`/`investigation`/`substantial doubt`), and a FinBERT/VADER sentiment-delta magnitude. Top-scoring diffs become `signals` (source='filing_diff'), get indexed into `rag_chunks` (source_type='filing'), and alert current holders. Nightly `job_filing_intel_refresh` auto-detects backfill-vs-incremental mode from whether `filings` is empty; idempotent on `accession_number` doubles as the resumability mechanism for a killed/restarted backfill (never re-fetches an already-ingested filing). `GET /api/filing-watch/<ticker>` (renamed from the playbook's suggested `/api/filings/<ticker>` — that path was already taken by `sec_8k_client.py`'s unrelated 8-K material-event endpoint, caught via the now-standard grep-before-naming habit) + a "Filing Watch" toggle in the existing Equity Research modal (before/after paragraph highlighting, red/green).

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
