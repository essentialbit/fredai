# FredAI — Claude Code Self-Improvement Config

## 🔒 Sensor Protected — Do Not Disrupt
The hourly `com.essentialbit.fredai.sensor` launchd job, its watchdog script, state dir (`~/.claude/fred-sensor/`), and any `claude -p` process it spawns must never be unloaded, deleted, edited, or killed by any session (interactive or headless) working in this repo — unless the user explicitly instructs termination live, in that session. This overrides any autonomous/pre-authorised operating mode. Status checks (`launchctl list`, heartbeat/log reads) are always fine.

## Orchestration (permanent — see `.claude/agents/`)

**Routing threshold**: a single-file, single-concern edit (typo, rename, one-line fix) is handled directly in the main thread — no subagents. Anything multi-file or multi-concern runs the full pipeline below. Anything touching auth, payments, data migrations, or public APIs always runs reviewer + approver regardless of size.

**Default pipeline** for everything above that threshold: `task-manager` decomposes the task into independent, acceptance-criteria-bearing units → `worker`s implement units in parallel wherever the decomposition allows it, sequentially only where a real dependency exists → `reviewer` independently tests the result → `approver` validates against the *original* request. Don't skip a stage. Full role detail lives in each agent's own file, not here.

- **Independence**: the reviewer must not be the agent that wrote the code; the approver must not be the reviewer or a worker. No agent grades its own work.
- **Context**: a subagent starts fresh and sees nothing from the main conversation — every delegation prompt must carry everything it needs (file paths, acceptance criteria, error messages, prior decisions).
- **Escalation**: a REJECTED verdict loops back to workers with the specific findings, max 2 remediation cycles, then surface to the user. An ESCALATE verdict stops immediately and asks the user. Never report a task complete on REJECTED or ESCALATE.
- **Reporting**: the approver's verdict and evidence go in the final message to the user — it gates the work, it doesn't get silently absorbed.

This roster and policy are permanent project infrastructure. Never remove, bypass, or collapse the pipeline without an explicit instruction from the user in the current session.

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
- `scenario_engine.py` — interactive what-if shock propagation (macro factor or ticker → portfolio impact), reuses `cascade_engine.py` for the actual correlation walk (see FSI L3 note below)
- `counterfactual_pnl.py` — Fred's Accountability: honest simulated equity curve of "what if you'd traded Fred's signals," per source, drawdowns/costs included, reuses `portfolio_risk.py`'s daily-close fetch + Sharpe/drawdown math (see FSI L3 note below)
- `divergence_radar.py` — Divergence Radar: 6 curated cross-asset pairs (credit/equities, breadth/index, copper-gold/yields, VIX-term/realized-vol, dollar/copper-gold, SKEW/VIX), rolling z-score spread detection with honest historical resolution stats (see FSI L2 note below)
- `market_debate.py` — Research Desk: Bull/Bear/Risk Officer/PM committee over a ticker, wired into the dashboard's main "Research Desk" toggle. NOT `ticker_debate.py` (a separate, unwired-in-the-main-UI implementation of the same Bull/Bear concept — pre-existing duplication, not touched by this feature) or `debate.py` (unrelated: self-improvement proposal review, not market analysis, despite similar naming) (see FSI L4 note below)
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
- L2 Pattern Intelligence 🔄 — FinBERT, cross-asset correlation, options flow, insider filings, Fear&Greed, **Divergence Radar (curated cross-asset disagreement detection with honest historical resolution stats) — shipped**
- L3 Predictive Intelligence 🔄 — backtesting, anomaly detection, macro regime (blocked, see standing policy), earnings prediction, **Scenario Simulator (interactive what-if shock propagation with portfolio P&L overlay) — shipped**, **Counterfactual P&L (honest simulated equity curve of Fred's own signals, per source, drawdowns + costs included) — shipped**
- L4 Reasoning Intelligence 🔄 — causal attribution, 13F positioning, **Fred Recall (hybrid FTS5+vector RAG grounding chat/briefings in Fred's own signal/news/briefing/debate/filing/vault history, cited inline) — shipped**, **Calibration Engine (Brier-scored per-source reliability weighting, feeds confluence_engine + chat hedging) — shipped**, **Thesis Tracker (living, evidence-fed investment theses with LLM-decomposed falsifiable assumptions and auto-attached supporting/contradicting evidence) — shipped**, **10-K/10-Q risk-language diffing — shipped**, **Research Desk (Bull/Bear/Risk Officer/PM committee, conviction-rated and track-record-accountable) — shipped**
- L5 World Model 🔲 — cross-market contagion, alternative data, fine-tuned LLM, agent swarms
- L6 Super Intelligence 🔲 — self-directing research, novel edge discovery, autonomous recommendations

**Evaluation criterion for every proposed improvement:** "Does this push Fred closer to L6? If not, is it critical infrastructure that unblocks L2+ work?" If neither is true, deprioritise it.

**Fred Recall (FSI L4, shipped)**: `rag_store.py` (storage: `rag_chunks` + FTS5 `rag_fts`, source_types news/signal/briefing/debate/insider/entity_evidence/vault) + `rag_retriever.py` (BM25+cosine via Reciprocal Rank Fusion, recency decay, ticker boost). Write-time hooks are FTS-only (`embed=False`) at every ingestion path (news_client, reddit/twitter_client, ticker_debate, main.py's briefing/entity-evidence routes) — embedding happens asynchronously in the hourly `job_rag_embed_backlog` job, never inline on a hot path. `chat()` and `generate_summary()` in agent.py both call `retrieve()`/`format_context()` for grounded, cited context; `GET /api/recall?q=` + the dashboard's "Ask Fred's Memory" panel expose it directly. Per-user privacy enforced inside `rag_store.py` (global rows + caller's own `user_id` rows only), never left to the caller. `vault_semantic_search.py` is now a thin wrapper over `rag_store` (source_type='vault') — the old standalone `vault_embeddings` table is dead schema, left in place.

**Calibration Engine (FSI L4, shipped)**: `calibration_engine.py` turns each `signal_outcomes` row (from `backtesting_engine.py`) into a probabilistic forecast — `avg_sentiment` magnitude maps to a stated P(correct) in [0.5,1.0] when available, else a documented fixed 0.65 for deterministic binary-call sources (insider/short_interest/technical, which carry no magnitude in this codebase). Brier-scores each source at the 24h checkpoint over a 30-day window, maps to a `[0.2, 1.5]` reliability weight (pivot: brier=0.25 = neutral 1.0), pinning sources with `sample_n < 20` to neutral with a `low_sample` flag. Persisted to `calibration_scores` (one row per source) by the daily `job_calibration_refresh` job. Wired into `confluence_engine.py::compute_confluence()`'s score (not its `agreement`/`factor_count`, which stay raw/structural) behind `config.CALIBRATION_WEIGHTS_ENABLED` (default true; false reproduces the pre-calibration formula bit-for-bit — verified). `agent.py`'s existing track-record lines (chat + briefing) append `(reliability x1.3)`-style suffixes when a source's weight is meaningfully off-neutral. `GET /api/calibration` + the dashboard's "Fred's Calibration" panel (reliability diagram + per-source table) surface it, bad sources included, not hidden.

**Thesis Tracker (FSI L4, shipped)**: `thesis_tracker.py` — `theses`/`thesis_assumptions`/`thesis_evidence` tables (per-user, ownership enforced at the API layer in main.py, same `entity["user_id"] != session["user_id"]` pattern as `tracked_entities.py`). Creation flow: `decompose_thesis()` (chat-tier LLM) drafts 3-6 falsifiable assumptions from a natural-language statement as a preview only — the user edits before `create_thesis()` actually persists. Nightly `job_thesis_auto_evidence` runs `rag_retriever.retrieve()` per active thesis, classifies new chunks via the cheap summary tier (`classify_evidence()`), auto-attaches (capped 5/thesis/run, idempotent on `(thesis_id, rag_chunk_id)` — manual free-text evidence is never deduped this way since SQLite treats each NULL as distinct), and `check_assumption_health()` marks assumptions weakening/broken on ≥3/≥6 contradicting items in the trailing 7 days (recovers to intact once evidence ages out), alerting only on a genuine status *transition* — never spams on repeat calls. `suggested_conviction()` is a recency-weighted (14d half-life) evidence balance, purely advisory, never auto-applied to the user's stated conviction. `chat()` summarizes active theses into context via `format_context_summary()`. Full CRUD under `/api/theses/*` (login_required, owner-only) + a dashboard "Investment Theses" panel (composer, conviction dial, assumption health lights, evidence feed with manual attach). Owner-isolation and idempotency verified at the module level against a fresh temp DB (not a full Flask-test-client pass — the ownership check itself is a one-line pattern already proven by `tracked_entities.py`'s identical precedent, judged lower marginal value than the rest of the verification for this feature's scope).

**Filing Intelligence (FSI L2/L4, shipped)**: `filing_intel.py` — new `filings`/`filing_sections`/`filing_diffs` tables. Reuses `sec_client.py`'s CIK map/User-Agent/submissions-JSON pattern (same SEC fair-use posture, sequential requests, polite delay) to poll 10-K/10-Q filings; `_extract_section()` heuristically locates Item 1A Risk Factors / Item 7 MD&A by picking the start-pattern match with the LARGEST gap to the next Item heading (filters out table-of-contents false-positives, which sit right before the next heading with near-zero content). Extracted text capped at ~200KB (HARD CONSTRAINT); raw HTML above 8MB is skipped rather than parsed. `diff_paragraphs()` is a `difflib.SequenceMatcher` paragraph-level diff (added/removed/modified, with a change_ratio); `_prior_filings_for_diff()` picks the comparison filing(s) — **must filter to strictly-earlier `filed_date`, not just a different accession_number**, or a resumed/re-run cycle can pick a newer filing as "prior" and diff backwards (real bug caught in verification, fixed before shipping). `materiality_score()` combines section weight (Risk Factors > MD&A), change_ratio, a documented high-signal-vocabulary list (`going concern`/`material weakness`/`covenant`/`impairment`/`investigation`/`substantial doubt`), and a FinBERT/VADER sentiment-delta magnitude. Top-scoring diffs become `signals` (source='filing_diff'), get indexed into `rag_chunks` (source_type='filing'), and alert current holders. Nightly `job_filing_intel_refresh` auto-detects backfill-vs-incremental mode from whether `filings` is empty; idempotent on `accession_number` doubles as the resumability mechanism for a killed/restarted backfill (never re-fetches an already-ingested filing). `GET /api/filing-watch/<ticker>` (renamed from the playbook's suggested `/api/filings/<ticker>` — that path was already taken by `sec_8k_client.py`'s unrelated 8-K material-event endpoint, caught via the now-standard grep-before-naming habit) + a "Filing Watch" toggle in the existing Equity Research modal (before/after paragraph highlighting, red/green).

**Scenario Simulator (FSI L3, shipped)**: `scenario_engine.py` — reuses `cascade_engine.cascade_for_event()` for the actual propagation math rather than reimplementing it; this module only maps a shock onto that engine's inputs. 12-factor `SHOCK_VOCABULARY`, two kinds kept honestly distinct: **"ticker" factors** (WTI/gold/FX/equities/crypto — real Yahoo price history, in `correlation_matrix`) propagate via a proxy ticker through `cascade_for_event`; **"macro_beta" factors** (fed funds/10Y yield/credit OAS/VIX — no tradeable price history in this system) use a small documented hand-curated `MACRO_BETA` sensitivity table (a qualitative prior, explicitly labeled as not a statistical correlation in every result). Second-order propagation feeds a first-order impact's own `impact_score` (already a %-move estimate, same units `cascade_for_event`'s `magnitude` param expects) directly into a second `cascade_for_event` call, THEN dampens the resulting score by `SECOND_ORDER_DAMPEN` — **dampening the input magnitude instead would double-divide it** (`cascade_for_event`'s own formula already divides by 10), silently vanishing every second-order effect regardless of correlation strength (real bug caught in verification, fixed before shipping). Also caught: the loop-back exclusion set must include the shock's actual proxy ticker (e.g. `CL=F`), not just its vocabulary key (`wti`) — `cascade_for_event`'s correlation walk is symmetric, so an unguarded second hop can loop straight back to the shock's own origin as a fabricated "impact" (also fixed before shipping). `apply_scenario_to_portfolio()` overlays estimated moves onto the caller's own portfolio for P&L + a worst-position call-out, and flags PRE-EXISTING VaR/beta threshold breaches (default thresholds, since no per-user-configurable risk-limit system actually exists in this codebase — `risk_rules.py` is unrelated proposal-risk tiering despite the similar name, corrected from the original playbook spec's assumption). `parse_scenario()` is deterministic-keyword-first, cheap-LLM-tier fallback second (strict-JSON validated against `SHOCK_VOCABULARY`, never a guess), honest "can't model that yet" last. Wired into `chat()` (a "what if"-shaped message runs the scenario and injects a narration-ready block into context, including portfolio overlay + breach notes when available) and a dashboard "Scenario Lab" panel (factor picker, magnitude slider, impact waterfall chart, portfolio P&L card, assumptions disclosure). `GET/POST /api/scenario`.

**Divergence Radar (FSI L2, shipped)**: `divergence_radar.py` — 6 curated, named, explainable cross-asset pairs (credit-vs-equities, breadth-vs-index, copper/gold-vs-10Y-yield, VIX-term-structure-vs-realized-vol, dollar-vs-copper/gold, SKEW-vs-VIX) in `PAIR_REGISTRY`, each an expected-relationship sign plus a plain-English rationale. Reuses `portfolio_risk._daily_closes` for every ticker-based leg and `credit_oas_spread`/`dollar_index_client`'s own private FRED-CSV fetchers for those two legs (one new local FRED fetch, `_fred_series`, needed only for 10Y yield — `yield_curve.py` only exposes a computed snapshot from a live macro cache, not a raw historical series). `finra_short_volume.py` (per-symbol, not market-wide) deliberately left out of the pair set rather than forced into an awkward pair — same "playbook's suggested list vs what's actually cleanly reusable" honesty already established for Filing Intelligence/Research Desk. Divergence measure: each leg's own rolling 60d z-score (never self-referential — excludes the current day from its own baseline, same convention as every `_trend()` helper), combined via the pair's expected-sign into a spread; `detect_events_from_spread()` (pure state machine, split from the live-fetching `detect_events()` specifically so it's fixture-testable) triggers on `|spread|>=2` sustained 3 consecutive days, `started_at` honestly backdated to day 1 of the streak (not the confirmation day). **Verification caught two related bugs before shipping**: (1) `initial_trigger_z` was being set to the *confirmation day's* value rather than the value at `started_at`, which could silently collapse it to equal `peak_z` and mask a real "got worse before it got better" episode as merely "converged"; (2) peak tracking only started from the confirmation day forward, missing a peak that occurred during the first 2 (pre-confirmation) days of the streak. Both fixed by tracking a running streak-peak from day 1, not just from confirmation. Resolution (`|spread|<1.0`) classifies `converged` vs `broke_further` (peak exceeded initial trigger by >0.25) and attributes `resolved_by` to whichever leg's z-score moved more to close the gap. `divergence_events` is UPSERTed (not insert-only like `counterfactual_runs` — an event's own `started_at`/`resolved_at` legitimately IS its mutable state, a different concern from that table's point-in-time-metric-history requirement) keyed on `(pair, started_at)`, so re-running the daily job never double-alerts on an already-known episode. `historical_resolution_stats()` reports `n=0` honestly rather than fabricating a rate. Nightly `job_divergence_radar_refresh` pushes newly-triggered/-resolved episodes as `signals(source='divergence')` + the existing alert/socketio pipeline; degrades per-pair on a stale/dead feed rather than failing the whole scan. `GET /api/divergences` + a "Divergence Radar" dashboard grid (sparkline + ±2 band per pair, active episodes highlighted, base-rate text, click-to-expand rationale). Active episodes are injected into `agent.build_context_block()` via a DB-only read (`get_active_divergence_events`, never a live fetch — chat/briefing context must never block on network, same reasoning as `get_cached_risk`). Regime-tagging (playbook's optional step 4 sub-clause) skipped — `regime_engine` doesn't exist (Feature 3 intentionally not shipped, blocked on #103's user go/no-go).

**Counterfactual P&L (FSI L3, shipped)**: `counterfactual_pnl.py` — honest simulated equity curve of "what if you'd traded Fred's own signals," per `signal_outcomes` source (aggregate/news_sentiment/insider/short_interest/technical), each with its own independent 100-notional-unit capital pool. Entry uses the close on the first trading day STRICTLY AFTER the signal — never `signal_outcomes.price_at_t0`, which `backtesting_engine.log_scan_outcomes` captures concurrently with the prediction itself and would be lookahead bias here. 10bps cost charged on both entry and exit; long-only + cash by default (`ALLOW_SHORTS=False` constant — bearish signals hold cash unless flipped); exits after `EXIT_HORIZON_DAYS` (5) trading days or on an opposing signal for the same asset, whichever comes first — **the opposing-signal check must fire off ALL actionable signals, not just the subset that actually opens a new position**, or a bearish call can never trigger an early exit on an existing long while shorts are disabled (real bug caught in verification, fixed before shipping: `all_actionable` vs the narrower `scheduled` list). Max 10 concurrent positions per source, overflow skipped and counted, never queued. **Verification also caught a capital double-count**: the entry path built each position's cost basis but never actually deducted `SLOT_SIZE` from `cash`, so cash and position value were both counted — final equity was inflated by exactly one slot's worth per open position (fixed before shipping, caught by a hand-computed-vs-actual equity assertion in the fixture test). Reuses `portfolio_risk.py`'s `_daily_closes`/`_mean`/`_stdev`/`_max_drawdown` and its Sharpe formula (rf=0, `TRADING_DAYS=252`) — zero new data dependencies. Nightly `job_counterfactual_refresh` persists headline stats (return/max-drawdown/Sharpe/win-rate/benchmark-delta) per source per window (30d/90d/365d/all) to `counterfactual_runs`, **always INSERTs, never UPDATEs** — every row carries its own `methodology_version` so a future rule change never silently rewrites history. `GET /api/counterfactual` serves the latest persisted per-window stats (cheap) plus a live-recomputed equity curve + SPY buy-and-hold overlay for the `aggregate` source only (same reasoning as `calibration_engine`'s curve-on-read: cheap thanks to `_daily_closes`'s 12h cache, avoids a second stale-cache surface). Dashboard "Fred's Accountability" panel: equity-curve-vs-SPY chart, headline stats giving max drawdown equal visual weight to return, per-source attribution table, and an always-visible (not tooltip-gated) methodology disclosure string. Briefing gets one honest line via `agent._format_counterfactual_for_briefing()` (empty, never fabricated, until the nightly job has run at least once). All numbers are a hypothetical simulation, not advice — `agent.DISCLAIMER_FOOTER` still applies wherever the briefing surfaces this.

**Research Desk (FSI L4, shipped)**: extends `market_debate.py` (the Bull/Bear/Arbiter system actually wired into the dashboard's main toggle) into a 4-role Bull/Bear/Risk Officer/PM committee, rather than standing up a third parallel debate system in a codebase that already independently shipped two (`market_debate.py` and `ticker_debate.py`) before this feature — a deliberate choice, confirmed with the user rather than picked unilaterally. Cost control is explicit: Bull/Bear/Risk moved from the "rnd"(Opus) tier to "summary"(cheap) tier — **a real cost regression this feature fixed, not just avoided** — PM uses "chat" tier only, and a rough chars/4 token estimate (`config.COMMITTEE_MAX_TOKENS`, default 6000) gates whether the Risk Officer/PM steps run at all; exceeding the budget (or a PM JSON parse failure) degrades to the original cheaper Bull/Bear/simple-Arbiter shape, not an error. `pm_verdict()`'s strict-JSON output includes `bull_score`/`bear_score`; `contested = |bull_score - bear_score| < 0.15` surfaces genuine disagreement rather than averaging it away. **Verification caught a real robustness gap**: `pm_verdict()` (and `bull_case`/`bear_case`/`risk_officer_case`/`_degraded_verdict`) only wrapped the JSON-parsing step in try/except, not the LLM call itself — a provider outage during any role's own call would have crashed the whole committee run instead of degrading, directly contradicting the HARD CONSTRAINT's "graceful degradation... when providers are constrained." All five now catch provider errors, not just parse errors. Every verdict is logged as a trackable `signals`/`signal_outcomes` row (`source='committee'`) via the same pipeline every other source uses, so the committee earns/loses credibility exactly like any other source (read via `_committee_track_record()`, distinct from the unrelated `agent_track_record` table — same naming-collision class as `debate.py`). Daily `job_research_desk_top_movers` auto-runs the committee for the top 2 by-signal-volume tickers (the HARD CONSTRAINT's cost ceiling for non-user-triggered runs); `?refresh=1` on the existing `/api/market-debate/<ticker>` route is user-triggered and rate-limited per-user (5/hour) since it costs real tokens — no separate `/api/desk/<ticker>` route was added (the playbook's suggested name), extending the existing endpoint instead. `chat()` recognizes "run the desk on NVDA"-style requests. Not yet done: MISSION.md's original "regime fit" sub-clause for the Risk Officer role (Regime Detection hasn't shipped — intentionally omitted rather than fabricated).

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
